# 日程模块与课表数据整合交接文档（后端）


## 1. 现状总览：当前有两套日历相关数据模型

在 `services/core/app/models.py` 里，现在存在**两条独立的数据线**，需要你在日历逻辑里统一：

| 数据线 | 表 | 用途 | 关键字段 |
|--------|-----|------|---------|
| ① 课表/DDL 线（既有） | `calendar_events` | 存放爬虫抓来的课程、作业 DDL | `kind`, `source`, `external_id` |
| ② 个人日程线（我实现） | `schedules` + `schedule_folders` + `schedule_tags` + `schedule_tag_associations` | 用户自定义日程（带文件夹和标签） | `folder_id`, `is_completed`, 标签多对多 |

> 架构文档（`docs/architecture.md`）原本设想"课表、个人日程、DDL 都映射为 `CalendarEvent`"，但个人日程因为需要**文件夹 + 标签 + 完成状态**，我单独建了 `schedules` 表。整合时由你决定是否做合并。

---

## 2. 我实现的「个人日程」模块（数据线 ②）

### 2.1 表结构

```
schedule_folders           —— 自定义文件夹
  id, user_id, name(唯一), created_at

schedules                  —— 日程
  id, user_id, folder_id(FK→schedule_folders, 可空), title, description,
  starts_at, ends_at, is_completed, created_at

schedule_tags              —— 自定义标签
  id, user_id, name(唯一), color(#rrggbb, 可空), created_at

schedule_tag_associations  —— 日程↔标签 多对多
  id, schedule_id(FK→schedules), tag_id(FK→schedule_tags)
  唯一约束 (schedule_id, tag_id)
```

### 2.2 可用的 API（前缀 `/api/v1`，全部需要 JWT）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/schedules` | 日程列表，支持 `folder_id` / `tag_id` / `start_date` / `end_date` / `is_completed` 过滤 |
| GET | `/schedules/{id}` | 单条日程（含嵌套 tags） |
| POST | `/schedules` | 创建日程 |
| PUT | `/schedules/{id}` | 部分更新（含 `is_completed`、`tag_ids`） |
| DELETE | `/schedules/{id}` | 删除日程 |
| GET | `/schedule-folders` | 文件夹列表 |
| POST/PUT/DELETE | `/schedule-folders[/{id}]` | 文件夹 CRUD |
| GET | `/schedule-tags` | 标签列表 |
| POST/PUT/DELETE | `/schedule-tags[/{id}]` | 标签 CRUD |
| GET | `/schedules/stats` | 按 day/week/month/year 统计完成数和标签分布 |

> 完整请求/响应示例见 `docs/schedule-api-handoff.md`（那是给前端看的 HTTP 文档，字段相同，可参考）。

### 2.3 关键业务规则

1. `ends_at` 必须**严格晚于** `starts_at`（schema 层校验）
2. 同名文件夹/标签在同一用户下唯一（409）
3. 删除文件夹 → 日程保留，`folder_id` 置 NULL
4. 删除标签 → 仅删关联记录，日程保留
5. 统计接口只统计 `is_completed=true` 的日程

---

## 3. 课表数据线现状（数据线 ①）

### 3.1 `calendar_events` 表（已存在，未改动）

```
calendar_events
  id, user_id, title, description, starts_at, ends_at,
  kind(ENUM: EVENT/COURSE/DEADLINE), source(默认 "manual"),
  external_id(可空)
  唯一约束 (user_id, source, external_id)
```

- `kind`：`course`=课表课程，`deadline`=作业 DDL，`event`=普通事件
- `source`：数据来源标识（如 `campus`、`manual`）
- `external_id`：爬虫侧唯一 ID，配合 `source` 用于**幂等去重**

### 3.2 爬虫防腐层（campus 服务）

`services/campus/campus/connectors/base.py` 定义了统一 DTO：

```python
class CampusItem(BaseModel):
    external_id: str
    title: str
    kind: str            # "course" / "task"
    starts_at: datetime | None
    ends_at: datetime | None
    due_at: datetime | None
```

`CampusConnector` 是 Protocol，`MockConnector` 是示例实现。campus 服务目前只有：
- `GET /health`
- `POST /sync/preview`（需 `X-Campus-Token` header，返回 `CampusItem` 列表）

**注意**：目前 campus 只返回 DTO，**写库逻辑还没有实现**。架构决策是「爬虫只解析返回 DTO，由 core 服务负责去重和写库」。这部分大概率就是你负责的整合点。

---


## 4. 你需要知道的技术细节

### 4.1 数据库访问

- ORM 模型：`services/core/app/models.py`（`CalendarEvent`、`Schedule`、`ScheduleFolder`、`ScheduleTag`、`ScheduleTagAssociation`）
- 异步会话：`services/core/app/db.py` 的 `get_session` / `SessionLocal`
- 数据库：PostgreSQL，async 驱动 `asyncpg`
- 迁移：`migrations/versions/`，新增表/字段需写 alembic migration

### 4.2 查我日程数据的代码示例

```python
# 拉取某时间段的个人日程（含标签）
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from services.core.app.models import Schedule

result = await session.scalars(
    select(Schedule)
    .where(
        Schedule.user_id == user_id,
        Schedule.starts_at >= start,
        Schedule.starts_at < end,
    )
)
schedules = list(result)
# 标签在 schedule_tag_associations + schedule_tags，可参考 api.py 的 _schedule_to_out
```
