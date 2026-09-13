import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import get_session
from .models import (
    CalendarEvent,
    FocusSession,
    RewardLedger,
    Schedule,
    ScheduleFolder,
    ScheduleTag,
    ScheduleTagAssociation,
    Task,
    User,
)
from .schemas import (
    BalanceOut,
    EventCreate,
    EventOut,
    FocusOut,
    FocusStart,
    LoginRequest,
    RegisterRequest,
    ScheduleCreate,
    ScheduleFolderCreate,
    ScheduleFolderOut,
    ScheduleFolderUpdate,
    ScheduleOut,
    ScheduleStatsOut,
    ScheduleTagCreate,
    ScheduleTagOut,
    ScheduleTagUpdate,
    ScheduleUpdate,
    TagCountItem,
    TaskCreate,
    TaskOut,
    TokenResponse,
)
from .security import create_token, current_user, password_hash

router = APIRouter(prefix="/api/v1")


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email.lower(), password_hash=password_hash.hash(body.password))
    session.add(user)
    await session.commit()
    return TokenResponse(access_token=create_token(user.id))


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not password_hash.verify(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return TokenResponse(access_token=create_token(user.id))


@router.get("/events", response_model=list[EventOut])
async def list_events(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    result = await session.scalars(
        select(CalendarEvent).where(CalendarEvent.user_id == user.id).order_by(CalendarEvent.starts_at)
    )
    return list(result)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(body: EventCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = CalendarEvent(user_id=user.id, **body.model_dump())
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    result = await session.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.due_at))
    return list(result)


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    task = Task(user_id=user.id, **body.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.post("/focus/start", response_model=FocusOut, status_code=status.HTTP_201_CREATED)
async def start_focus(body: FocusStart, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    focus = FocusSession(user_id=user.id, planned_minutes=body.planned_minutes)
    session.add(focus)
    await session.commit()
    await session.refresh(focus)
    return focus


@router.post("/focus/{focus_id}/finish", response_model=FocusOut)
async def finish_focus(focus_id: uuid.UUID, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    focus = await session.scalar(
        select(FocusSession).where(FocusSession.id == focus_id, FocusSession.user_id == user.id)
    )
    if not focus:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Focus session not found")
    if focus.finished_at is None:
        focus.finished_at = datetime.now(UTC)
        elapsed = (focus.finished_at - focus.started_at).total_seconds()
        if elapsed >= focus.planned_minutes * 60 * 0.8:
            session.add(RewardLedger(user_id=user.id, amount=focus.planned_minutes, reason="focus_completed", reference_id=f"focus:{focus.id}"))
        await session.commit()
        await session.refresh(focus)
    return focus


@router.get("/rewards/balance", response_model=BalanceOut)
async def reward_balance(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    balance = await session.scalar(select(func.coalesce(func.sum(RewardLedger.amount), 0)).where(RewardLedger.user_id == user.id))
    return BalanceOut(balance=balance or 0)


# ──────────────── Schedule Folder APIs ────────────────


@router.get("/schedule-folders", response_model=list[ScheduleFolderOut])
async def list_folders(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ScheduleFolder)
        .where(ScheduleFolder.user_id == user.id)
        .order_by(ScheduleFolder.created_at)
    )
    return list(result)


@router.post("/schedule-folders", response_model=ScheduleFolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: ScheduleFolderCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id, ScheduleFolder.name == body.name
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists")
    folder = ScheduleFolder(user_id=user.id, name=body.name)
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return folder


@router.put("/schedule-folders/{folder_id}", response_model=ScheduleFolderOut)
async def update_folder(
    folder_id: uuid.UUID,
    body: ScheduleFolderUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id, ScheduleFolder.user_id == user.id
        )
    )
    if not folder:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    conflict = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id,
            ScheduleFolder.name == body.name,
            ScheduleFolder.id != folder_id,
        )
    )
    if conflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists")
    folder.name = body.name
    await session.commit()
    await session.refresh(folder)
    return folder


@router.delete("/schedule-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id, ScheduleFolder.user_id == user.id
        )
    )
    if not folder:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    # 将属于该文件夹的日程设为无文件夹
    schedules = (await session.scalars(
        select(Schedule).where(Schedule.folder_id == folder_id)
    )).all()
    for s in schedules:
        s.folder_id = None
    await session.delete(folder)
    await session.commit()
    return None


# ──────────────── Schedule Tag APIs ────────────────


@router.get("/schedule-tags", response_model=list[ScheduleTagOut])
async def list_tags(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    result = await session.scalars(
        select(ScheduleTag)
        .where(ScheduleTag.user_id == user.id)
        .order_by(ScheduleTag.created_at)
    )
    return list(result)


@router.post("/schedule-tags", response_model=ScheduleTagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: ScheduleTagCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.user_id == user.id, ScheduleTag.name == body.name
        )
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists")
    tag = ScheduleTag(user_id=user.id, name=body.name, color=body.color)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


@router.put("/schedule-tags/{tag_id}", response_model=ScheduleTagOut)
async def update_tag(
    tag_id: uuid.UUID,
    body: ScheduleTagUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id, ScheduleTag.user_id == user.id
        )
    )
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    if body.name is not None:
        conflict = await session.scalar(
            select(ScheduleTag).where(
                ScheduleTag.user_id == user.id,
                ScheduleTag.name == body.name,
                ScheduleTag.id != tag_id,
            )
        )
        if conflict:
            raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists")
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    await session.commit()
    await session.refresh(tag)
    return tag


@router.delete("/schedule-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id, ScheduleTag.user_id == user.id
        )
    )
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    await session.delete(tag)
    await session.commit()
    return None


# ──────────────── Schedule (日程) APIs ────────────────


async def _schedule_to_out(schedule: Schedule, session: AsyncSession) -> ScheduleOut:
    """将 Schedule ORM 对象转为 ScheduleOut，包含关联的 tags。"""
    assoc_result = await session.scalars(
        select(ScheduleTagAssociation).where(
            ScheduleTagAssociation.schedule_id == schedule.id
        )
    )
    assocs = list(assoc_result)
    tag_ids = [a.tag_id for a in assocs]
    tags: list[ScheduleTagOut] = []
    if tag_ids:
        tag_result = await session.scalars(
            select(ScheduleTag).where(ScheduleTag.id.in_(tag_ids))
        )
        tags = [
            ScheduleTagOut.model_validate(t) for t in tag_result
        ]
    return ScheduleOut(
        id=schedule.id,
        folder_id=schedule.folder_id,
        title=schedule.title,
        description=schedule.description,
        starts_at=schedule.starts_at,
        ends_at=schedule.ends_at,
        is_completed=schedule.is_completed,
        tags=tags,
        created_at=schedule.created_at,
    )


async def _set_schedule_tags(
    schedule_id: uuid.UUID, tag_ids: list[uuid.UUID], session: AsyncSession
) -> None:
    """设置日程的标签（先删后建）。"""
    existing = (await session.scalars(
        select(ScheduleTagAssociation).where(
            ScheduleTagAssociation.schedule_id == schedule_id
        )
    )).all()
    for assoc in existing:
        await session.delete(assoc)
    # 先执行删除，避免与后续插入的新关联发生 (schedule_id, tag_id) 唯一约束冲突
    await session.flush()
    # 去重，防止传入重复 tag_id 导致唯一约束冲突
    for tag_id in dict.fromkeys(tag_ids):
        session.add(ScheduleTagAssociation(schedule_id=schedule_id, tag_id=tag_id))


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    folder_id: uuid.UUID | None = Query(None, description="按文件夹筛选"),
    tag_id: uuid.UUID | None = Query(None, description="按标签筛选"),
    start_date: datetime | None = Query(None, description="开始日期筛选（含）"),
    end_date: datetime | None = Query(None, description="结束日期筛选（含）"),
    is_completed: bool | None = Query(None, description="按完成状态筛选"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(Schedule).where(Schedule.user_id == user.id)

    if folder_id is not None:
        query = query.where(Schedule.folder_id == folder_id)
    if start_date is not None:
        query = query.where(Schedule.starts_at >= start_date)
    if end_date is not None:
        query = query.where(Schedule.ends_at <= end_date)
    if is_completed is not None:
        query = query.where(Schedule.is_completed == is_completed)

    # tag filter: join via association table
    if tag_id is not None:
        query = query.where(
            Schedule.id.in_(
                select(ScheduleTagAssociation.schedule_id).where(
                    ScheduleTagAssociation.tag_id == tag_id
                )
            )
        )

    query = query.order_by(Schedule.starts_at)
    result = await session.scalars(query)
    schedules = list(result)
    return [await _schedule_to_out(s, session) for s in schedules]


# ──────────────── Schedule Statistics APIs ────────────────


@router.get("/schedules/stats", response_model=ScheduleStatsOut)
async def schedule_stats(
    period: str = Query("month", pattern=r"^(day|week|month|year)$"),
    date: str | None = Query(None, description="基准日期 ISO 格式，默认今天"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """按天/周/月/年 统计已完成日程数量和标签分布（饼状图数据）。"""
    base_date = datetime.now(UTC) if date is None else datetime.fromisoformat(date)

    if period == "day":
        start = base_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "week":
        start = base_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=base_date.weekday()
        )
        end = start + timedelta(days=7)
    elif period == "month":
        start = base_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if base_date.month == 12:
            end = base_date.replace(year=base_date.year + 1, month=1, day=1)
        else:
            end = base_date.replace(month=base_date.month + 1, day=1)
    else:  # year
        start = base_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = base_date.replace(year=base_date.year + 1, month=1, day=1)

    # 查询该时间段内已完成的日程
    schedules = (
        await session.scalars(
            select(Schedule).where(
                Schedule.user_id == user.id,
                Schedule.is_completed == True,
                Schedule.starts_at >= start,
                Schedule.starts_at < end,
            )
        )
    ).all()

    total_completed = len(schedules)

    # 按标签统计
    tag_count_map: dict[str, dict] = {}  # tag_id -> {tag_name, tag_color, count}
    untagged_count = 0

    for s in schedules:
        assocs = (
            await session.scalars(
                select(ScheduleTagAssociation).where(
                    ScheduleTagAssociation.schedule_id == s.id
                )
            )
        ).all()
        if not assocs:
            untagged_count += 1
        else:
            tag_ids = [a.tag_id for a in assocs]
            tags = (
                await session.scalars(
                    select(ScheduleTag).where(ScheduleTag.id.in_(tag_ids))
                )
            ).all()
            for t in tags:
                key = str(t.id)
                if key not in tag_count_map:
                    tag_count_map[key] = {
                        "tag_id": t.id,
                        "tag_name": t.name,
                        "tag_color": t.color,
                        "count": 0,
                    }
                tag_count_map[key]["count"] += 1

    tag_counts: list[TagCountItem] = []
    for item in tag_count_map.values():
        tag_counts.append(
            TagCountItem(
                tag_id=item["tag_id"],
                tag_name=item["tag_name"],
                tag_color=item["tag_color"],
                count=item["count"],
            )
        )
    if untagged_count > 0:
        tag_counts.append(
            TagCountItem(tag_id=None, tag_name="未分类", tag_color=None, count=untagged_count)
        )

    return ScheduleStatsOut(
        period=period,
        total_completed=total_completed,
        tag_counts=tag_counts,
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return await _schedule_to_out(schedule, session)


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    # validate folder belongs to user if provided
    if body.folder_id:
        folder = await session.scalar(
            select(ScheduleFolder).where(
                ScheduleFolder.id == body.folder_id,
                ScheduleFolder.user_id == user.id,
            )
        )
        if not folder:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")

    tag_ids = body.tag_ids
    schedule = Schedule(
        user_id=user.id,
        folder_id=body.folder_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )
    session.add(schedule)
    await session.flush()  # get schedule.id

    await _set_schedule_tags(schedule.id, tag_ids, session)
    await session.commit()
    await session.refresh(schedule)
    return await _schedule_to_out(schedule, session)


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")

    if body.folder_id is not None:
        if body.folder_id != schedule.folder_id:
            # 允许设为 None（移除文件夹）
            if body.folder_id is not None:
                folder = await session.scalar(
                    select(ScheduleFolder).where(
                        ScheduleFolder.id == body.folder_id,
                        ScheduleFolder.user_id == user.id,
                    )
                )
                if not folder:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
            schedule.folder_id = body.folder_id

    update_fields = ("title", "description", "starts_at", "ends_at", "is_completed")
    for field in update_fields:
        value = getattr(body, field, None)
        if value is not None:
            setattr(schedule, field, value)

    # 验证时间区间
    if schedule.ends_at <= schedule.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at")

    if body.tag_ids is not None:
        await _set_schedule_tags(schedule.id, body.tag_ids, session)

    await session.commit()
    await session.refresh(schedule)
    return await _schedule_to_out(schedule, session)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id, Schedule.user_id == user.id
        )
    )
    if not schedule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    await session.delete(schedule)
    await session.commit()
    return None


@router.get("/media/tracks")
async def media_tracks(_: User = Depends(current_user)):
    return {"items": [{"id": "white-noise", "title": "White noise", "kind": "builtin", "url": None}]}

