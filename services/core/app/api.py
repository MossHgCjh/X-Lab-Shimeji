import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    FocusStart,
    FocusStatusOut,
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


# ──────────────── Built-in Media Assets ────────────────

NOISE_DIR = Path(__file__).resolve().parent.parent / "assets" / "noise"

NOISE_FILES = {
    "white": NOISE_DIR / "white.ogg",
}


# ──────────────── Focus Helpers ────────────────


def as_utc(value: datetime) -> datetime:
    """Normalize DB datetimes to UTC.

    SQLite used by tests may return naive datetimes even when the model
    declares timezone=True, while PostgreSQL returns timezone-aware values.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def focus_status(focus: FocusSession) -> FocusStatusOut:
    """Convert a focus ORM record into the API status representation."""
    now = datetime.now(UTC)

    started_at = as_utc(focus.started_at)

    if focus.finished_at is not None:
        end = as_utc(focus.finished_at)
    else:
        end = now

    elapsed = max(
        0,
        int((end - started_at).total_seconds()),
    )

    planned = focus.planned_minutes * 60
    remaining = max(0, planned - elapsed)

    if focus.end_reason == "cancelled":
        current_status = "cancelled"
    elif focus.finished_at is not None:
        current_status = "completed"
    elif remaining == 0:
        current_status = "expired"
    else:
        current_status = "running"

    return FocusStatusOut(
        id=focus.id,
        schedule_id=focus.schedule_id,
        planned_minutes=focus.planned_minutes,
        started_at=focus.started_at,
        finished_at=focus.finished_at,
        end_reason=focus.end_reason,
        status=current_status,
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
    )


# ──────────────── Authentication APIs ────────────────


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    if await session.scalar(
        select(User).where(User.email == body.email.lower())
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Email already registered",
        )

    user = User(
        email=body.email.lower(),
        password_hash=password_hash.hash(body.password),
    )

    session.add(user)
    await session.commit()

    return TokenResponse(
        access_token=create_token(user.id),
    )


@router.post(
    "/auth/login",
    response_model=TokenResponse,
)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    user = await session.scalar(
        select(User).where(User.email == body.email.lower())
    )

    if not user or not password_hash.verify(
        body.password,
        user.password_hash,
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid credentials",
        )

    return TokenResponse(
        access_token=create_token(user.id),
    )


# ──────────────── Event APIs ────────────────


@router.get(
    "/events",
    response_model=list[EventOut],
)
async def list_events(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.user_id == user.id)
        .order_by(CalendarEvent.starts_at)
    )

    return list(result)


@router.post(
    "/events",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_event(
    body: EventCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = CalendarEvent(
        user_id=user.id,
        **body.model_dump(),
    )

    session.add(event)
    await session.commit()
    await session.refresh(event)

    return event


# ──────────────── Task APIs ────────────────


@router.get(
    "/tasks",
    response_model=list[TaskOut],
)
async def list_tasks(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(Task.due_at)
    )

    return list(result)


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    body: TaskCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    task = Task(
        user_id=user.id,
        **body.model_dump(),
    )

    session.add(task)
    await session.commit()
    await session.refresh(task)

    return task


# ──────────────── Focus APIs ────────────────


@router.post(
    "/focus/start",
    response_model=FocusStatusOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_focus(
    body: FocusStart,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    active = await session.scalar(
        select(FocusSession).where(
            FocusSession.user_id == user.id,
            FocusSession.finished_at.is_(None),
        )
    )

    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A focus session is already running",
        )

    focus = FocusSession(
        user_id=user.id,
        planned_minutes=body.planned_minutes,
    )

    session.add(focus)
    await session.commit()
    await session.refresh(focus)

    return focus_status(focus)


# NOTE:
# /focus/current and /focus/history must appear before /focus/{focus_id},
# otherwise FastAPI may try to interpret "current" or "history" as UUIDs.


@router.get(
    "/focus/current",
    response_model=FocusStatusOut | None,
)
async def current_focus(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    focus = await session.scalar(
        select(FocusSession)
        .where(
            FocusSession.user_id == user.id,
            FocusSession.finished_at.is_(None),
        )
        .order_by(FocusSession.started_at.desc())
    )

    if focus is None:
        return None

    return focus_status(focus)


@router.get(
    "/focus/history",
    response_model=list[FocusStatusOut],
)
async def focus_history(
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(FocusSession)
        .where(
            FocusSession.user_id == user.id,
        )
        .order_by(FocusSession.started_at.desc())
        .limit(limit)
    )

    return [
        focus_status(item)
        for item in result
    ]


@router.get(
    "/focus/{focus_id}",
    response_model=FocusStatusOut,
)
async def get_focus(
    focus_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    focus = await session.scalar(
        select(FocusSession).where(
            FocusSession.id == focus_id,
            FocusSession.user_id == user.id,
        )
    )

    if focus is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Focus session not found",
        )

    return focus_status(focus)


@router.post(
    "/focus/{focus_id}/finish",
    response_model=FocusStatusOut,
)
async def finish_focus(
    focus_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    focus = await session.scalar(
        select(FocusSession).where(
            FocusSession.id == focus_id,
            FocusSession.user_id == user.id,
        )
    )

    if focus is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Focus session not found",
        )

    if focus.finished_at is not None:
        if focus.end_reason == "cancelled":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cancelled focus session cannot be finished",
            )

        return focus_status(focus)

    focus.finished_at = datetime.now(UTC)
    focus.end_reason = "completed"

    elapsed = (
        focus.finished_at
        - as_utc(focus.started_at)
    ).total_seconds()

    if elapsed >= focus.planned_minutes * 60 * 0.8:
        session.add(
            RewardLedger(
                user_id=user.id,
                amount=focus.planned_minutes,
                reason="focus_completed",
                reference_id=f"focus:{focus.id}",
            )
        )

    await session.commit()
    await session.refresh(focus)

    return focus_status(focus)


@router.post(
    "/focus/{focus_id}/cancel",
    response_model=FocusStatusOut,
)
async def cancel_focus(
    focus_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    focus = await session.scalar(
        select(FocusSession).where(
            FocusSession.id == focus_id,
            FocusSession.user_id == user.id,
        )
    )

    if focus is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Focus session not found",
        )

    if focus.finished_at is not None:
        if focus.end_reason != "cancelled":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Completed focus session cannot be cancelled",
            )

        return focus_status(focus)

    focus.finished_at = datetime.now(UTC)
    focus.end_reason = "cancelled"

    await session.commit()
    await session.refresh(focus)

    return focus_status(focus)


# ──────────────── Reward APIs ────────────────


@router.get(
    "/rewards/balance",
    response_model=BalanceOut,
)
async def reward_balance(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    balance = await session.scalar(
        select(
            func.coalesce(
                func.sum(RewardLedger.amount),
                0,
            )
        ).where(
            RewardLedger.user_id == user.id,
        )
    )

    return BalanceOut(
        balance=balance or 0,
    )


# ──────────────── Schedule Folder APIs ────────────────


@router.get(
    "/schedule-folders",
    response_model=list[ScheduleFolderOut],
)
async def list_folders(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(ScheduleFolder)
        .where(
            ScheduleFolder.user_id == user.id,
        )
        .order_by(
            ScheduleFolder.created_at,
        )
    )

    return list(result)


@router.post(
    "/schedule-folders",
    response_model=ScheduleFolderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    body: ScheduleFolderCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id,
            ScheduleFolder.name == body.name,
        )
    )

    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Folder name already exists",
        )

    folder = ScheduleFolder(
        user_id=user.id,
        name=body.name,
    )

    session.add(folder)
    await session.commit()
    await session.refresh(folder)

    return folder


@router.put(
    "/schedule-folders/{folder_id}",
    response_model=ScheduleFolderOut,
)
async def update_folder(
    folder_id: uuid.UUID,
    body: ScheduleFolderUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id,
            ScheduleFolder.user_id == user.id,
        )
    )

    if not folder:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Folder not found",
        )

    conflict = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.user_id == user.id,
            ScheduleFolder.name == body.name,
            ScheduleFolder.id != folder_id,
        )
    )

    if conflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Folder name already exists",
        )

    folder.name = body.name

    await session.commit()
    await session.refresh(folder)

    return folder


@router.delete(
    "/schedule-folders/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_folder(
    folder_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    folder = await session.scalar(
        select(ScheduleFolder).where(
            ScheduleFolder.id == folder_id,
            ScheduleFolder.user_id == user.id,
        )
    )

    if not folder:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Folder not found",
        )

    # 将属于该文件夹的日程设为无文件夹。
    schedules = (
        await session.scalars(
            select(Schedule).where(
                Schedule.folder_id == folder_id,
            )
        )
    ).all()

    for schedule in schedules:
        schedule.folder_id = None

    await session.delete(folder)
    await session.commit()

    return None


# ──────────────── Schedule Tag APIs ────────────────


@router.get(
    "/schedule-tags",
    response_model=list[ScheduleTagOut],
)
async def list_tags(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.scalars(
        select(ScheduleTag)
        .where(
            ScheduleTag.user_id == user.id,
        )
        .order_by(
            ScheduleTag.created_at,
        )
    )

    return list(result)


@router.post(
    "/schedule-tags",
    response_model=ScheduleTagOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_tag(
    body: ScheduleTagCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.user_id == user.id,
            ScheduleTag.name == body.name,
        )
    )

    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tag name already exists",
        )

    tag = ScheduleTag(
        user_id=user.id,
        name=body.name,
        color=body.color,
    )

    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    return tag


@router.put(
    "/schedule-tags/{tag_id}",
    response_model=ScheduleTagOut,
)
async def update_tag(
    tag_id: uuid.UUID,
    body: ScheduleTagUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id,
            ScheduleTag.user_id == user.id,
        )
    )

    if not tag:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Tag not found",
        )

    if body.name is not None:
        conflict = await session.scalar(
            select(ScheduleTag).where(
                ScheduleTag.user_id == user.id,
                ScheduleTag.name == body.name,
                ScheduleTag.id != tag_id,
            )
        )

        if conflict:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Tag name already exists",
            )

        tag.name = body.name

    if body.color is not None:
        tag.color = body.color

    await session.commit()
    await session.refresh(tag)

    return tag


@router.delete(
    "/schedule-tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tag(
    tag_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    tag = await session.scalar(
        select(ScheduleTag).where(
            ScheduleTag.id == tag_id,
            ScheduleTag.user_id == user.id,
        )
    )

    if not tag:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Tag not found",
        )

    await session.delete(tag)
    await session.commit()

    return None


# ──────────────── Schedule Helpers ────────────────


async def _schedule_to_out(
    schedule: Schedule,
    session: AsyncSession,
) -> ScheduleOut:
    """将 Schedule ORM 对象转为 ScheduleOut，包含关联的 tags。"""
    assoc_result = await session.scalars(
        select(ScheduleTagAssociation).where(
            ScheduleTagAssociation.schedule_id == schedule.id,
        )
    )

    assocs = list(assoc_result)
    tag_ids = [
        association.tag_id
        for association in assocs
    ]

    tags: list[ScheduleTagOut] = []

    if tag_ids:
        tag_result = await session.scalars(
            select(ScheduleTag).where(
                ScheduleTag.id.in_(tag_ids),
            )
        )

        tags = [
            ScheduleTagOut.model_validate(tag)
            for tag in tag_result
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
    schedule_id: uuid.UUID,
    tag_ids: list[uuid.UUID],
    session: AsyncSession,
) -> None:
    """设置日程的标签（先删后建）。"""
    existing = (
        await session.scalars(
            select(ScheduleTagAssociation).where(
                ScheduleTagAssociation.schedule_id == schedule_id,
            )
        )
    ).all()

    for association in existing:
        await session.delete(association)

    # 先执行删除，避免与后续插入的新关联发生
    # (schedule_id, tag_id) 唯一约束冲突。
    await session.flush()

    # 去重，防止传入重复 tag_id 导致唯一约束冲突。
    for tag_id in dict.fromkeys(tag_ids):
        session.add(
            ScheduleTagAssociation(
                schedule_id=schedule_id,
                tag_id=tag_id,
            )
        )


# ──────────────── Schedule APIs ────────────────


@router.get(
    "/schedules",
    response_model=list[ScheduleOut],
)
async def list_schedules(
    folder_id: uuid.UUID | None = Query(
        None,
        description="按文件夹筛选",
    ),
    tag_id: uuid.UUID | None = Query(
        None,
        description="按标签筛选",
    ),
    start_date: datetime | None = Query(
        None,
        description="开始日期筛选（含）",
    ),
    end_date: datetime | None = Query(
        None,
        description="结束日期筛选（含）",
    ),
    is_completed: bool | None = Query(
        None,
        description="按完成状态筛选",
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    query = select(Schedule).where(
        Schedule.user_id == user.id,
    )

    if folder_id is not None:
        query = query.where(
            Schedule.folder_id == folder_id,
        )

    if start_date is not None:
        query = query.where(
            Schedule.starts_at >= start_date,
        )

    if end_date is not None:
        query = query.where(
            Schedule.ends_at <= end_date,
        )

    if is_completed is not None:
        query = query.where(
            Schedule.is_completed == is_completed,
        )

    if tag_id is not None:
        query = query.where(
            Schedule.id.in_(
                select(
                    ScheduleTagAssociation.schedule_id,
                ).where(
                    ScheduleTagAssociation.tag_id == tag_id,
                )
            )
        )

    query = query.order_by(
        Schedule.starts_at,
    )

    result = await session.scalars(query)
    schedules = list(result)

    return [
        await _schedule_to_out(schedule, session)
        for schedule in schedules
    ]


# IMPORTANT:
# /schedules/stats must appear before /schedules/{schedule_id}.


@router.get(
    "/schedules/stats",
    response_model=ScheduleStatsOut,
)
async def schedule_stats(
    period: str = Query(
        "month",
        pattern=r"^(day|week|month|year)$",
    ),
    date: str | None = Query(
        None,
        description="基准日期 ISO 格式，默认今天",
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """按天/周/月/年统计已完成日程数量和标签分布。"""
    base_date = (
        datetime.now(UTC)
        if date is None
        else datetime.fromisoformat(date)
    )

    if period == "day":
        start = base_date.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = start + timedelta(days=1)

    elif period == "week":
        start = base_date.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) - timedelta(
            days=base_date.weekday(),
        )
        end = start + timedelta(days=7)

    elif period == "month":
        start = base_date.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        if base_date.month == 12:
            end = base_date.replace(
                year=base_date.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            end = base_date.replace(
                month=base_date.month + 1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

    else:
        start = base_date.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = base_date.replace(
            year=base_date.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    schedules = (
        await session.scalars(
            select(Schedule).where(
                Schedule.user_id == user.id,
                Schedule.is_completed.is_(True),
                Schedule.starts_at >= start,
                Schedule.starts_at < end,
            )
        )
    ).all()

    total_completed = len(schedules)

    tag_count_map: dict[str, dict] = {}
    untagged_count = 0

    for schedule in schedules:
        associations = (
            await session.scalars(
                select(ScheduleTagAssociation).where(
                    ScheduleTagAssociation.schedule_id == schedule.id,
                )
            )
        ).all()

        if not associations:
            untagged_count += 1
            continue

        tag_ids = [
            association.tag_id
            for association in associations
        ]

        tags = (
            await session.scalars(
                select(ScheduleTag).where(
                    ScheduleTag.id.in_(tag_ids),
                )
            )
        ).all()

        for tag in tags:
            key = str(tag.id)

            if key not in tag_count_map:
                tag_count_map[key] = {
                    "tag_id": tag.id,
                    "tag_name": tag.name,
                    "tag_color": tag.color,
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
            TagCountItem(
                tag_id=None,
                tag_name="未分类",
                tag_color=None,
                count=untagged_count,
            )
        )

    return ScheduleStatsOut(
        period=period,
        total_completed=total_completed,
        tag_counts=tag_counts,
    )


@router.get(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
)
async def get_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == user.id,
        )
    )

    if not schedule:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Schedule not found",
        )

    return await _schedule_to_out(
        schedule,
        session,
    )


@router.post(
    "/schedules",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.folder_id:
        folder = await session.scalar(
            select(ScheduleFolder).where(
                ScheduleFolder.id == body.folder_id,
                ScheduleFolder.user_id == user.id,
            )
        )

        if not folder:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Folder not found",
            )

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

    # Flush first so schedule.id exists before creating tag associations.
    await session.flush()

    await _set_schedule_tags(
        schedule.id,
        tag_ids,
        session,
    )

    await session.commit()
    await session.refresh(schedule)

    return await _schedule_to_out(
        schedule,
        session,
    )


@router.put(
    "/schedules/{schedule_id}",
    response_model=ScheduleOut,
)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == user.id,
        )
    )

    if not schedule:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Schedule not found",
        )

    if body.folder_id is not None:
        if body.folder_id != schedule.folder_id:
            folder = await session.scalar(
                select(ScheduleFolder).where(
                    ScheduleFolder.id == body.folder_id,
                    ScheduleFolder.user_id == user.id,
                )
            )

            if not folder:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    "Folder not found",
                )

            schedule.folder_id = body.folder_id

    update_fields = (
        "title",
        "description",
        "starts_at",
        "ends_at",
        "is_completed",
    )

    for field in update_fields:
        value = getattr(
            body,
            field,
            None,
        )

        if value is not None:
            setattr(
                schedule,
                field,
                value,
            )

    if schedule.ends_at <= schedule.starts_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ends_at must be after starts_at",
        )

    if body.tag_ids is not None:
        await _set_schedule_tags(
            schedule.id,
            body.tag_ids,
            session,
        )

    await session.commit()
    await session.refresh(schedule)

    return await _schedule_to_out(
        schedule,
        session,
    )


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    schedule = await session.scalar(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == user.id,
        )
    )

    if not schedule:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Schedule not found",
        )

    await session.delete(schedule)
    await session.commit()

    return None


# ──────────────── Media APIs ────────────────


@router.get("/media/tracks")
async def media_tracks(
    _: User = Depends(current_user),
):
    return {
        "items": [
            {
                "id": "white-noise",
                "title": "White Noise",
                "kind": "builtin",
                "url": "/api/v1/media/noise/white",
            }
        ]
    }


@router.get("/media/noise/{kind}")
async def get_noise(
    kind: str,
    _: User = Depends(current_user),
):
    path = NOISE_FILES.get(kind)

    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Unknown noise type",
        )

    if not path.is_file():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Noise asset is missing",
        )

    return FileResponse(
        path,
        media_type="audio/ogg",
    )