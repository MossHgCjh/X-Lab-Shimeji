# 日程模块调试指南

## 环境准备（已踩过的坑）

在启动之前，确保以下问题已修复：

### 坑 1：缺少 `.env` 文件
**现象**：`docker compose up` 报 `required variable MINIO_ROOT_USER is missing`
**修复**：`cp .env.example .env`

### 坑 2：Docker Hub 拉取超时
**现象**：`docker compose build` 报 `dial tcp ... i/o timeout`，无法拉取 `python:3.12-slim`
**修复**：先手动拉取基础镜像 `docker pull python:3.12-slim`（如果已有缓存则跳过）

### 坑 3：`.env` 中密码不匹配
**现象**：Alembic 迁移报 `password authentication failed for user "study"`
**原因**：`.env.example` 中 `APP_DATABASE_URL` 的密码是 `study`，但 `POSTGRES_PASSWORD` 是 `change-me`，两者不一致
**修复**：已将 `.env` 和 `.env.example` 中 `APP_DATABASE_URL` 的密码改为 `change-me`

### 坑 4：`cors_origins` 类型解析失败
**现象**：API 容器启动报 `SettingsError: error parsing value for field "cors_origins"`
**原因**：pydantic-settings 对 `list[str]` 类型字段会先尝试 `json.loads()`，在 validator 运行前就失败
**修复**：`config.py` 中 `cors_origins` 改为 `str` 类型，通过 `get_cors_origins()` 方法解析

### 坑 5：Alembic 的 psycopg2 缺失
**现象**：`alembic upgrade head` 报 `ModuleNotFoundError: No module named 'psycopg2'`
**原因**：`env.py` 替换 `+asyncpg` 为空字符串，SQLAlchemy 默认用 `psycopg2`（v2），但项目只有 `psycopg`（v3）
**修复**：`env.py` 改为 `replace("+asyncpg", "+psycopg")`

### 坑 6：`/schedules/stats` 路由被 `/{schedule_id}` 拦截
**现象**：访问 stats 返回 `Input should be a valid UUID, invalid character: found 's' at 1`
**原因**：FastAPI 按注册顺序匹配路由，`/{schedule_id}` 在 `/stats` 之前注册，"stats" 被当成了 UUID
**修复**：将 stats 路由定义移到 `get_schedule` 路由之前

### 坑 7：Caddy 强制 HTTPS
**现象**：`curl http://localhost/...` 返回空
**原因**：Caddy 将 HTTP 308 重定向到 HTTPS
**解决**：本地测试用 `curl -k https://localhost/...`，或直接访问 `http://localhost:8000/docs`（直连 API 容器）

### 坑 8：更新日程时重复 tag_ids 触发 500
**现象**：`PUT /schedules/{id}` 带 `tag_ids` 时返回 500 `Internal Server Error`
**原因**：`_set_schedule_tags` 先删除旧关联再插入新关联，但 SQLAlchemy 不保证 DELETE 在 INSERT 之前执行，导致 `(schedule_id, tag_id)` 唯一约束冲突
**修复**：删除后加 `await session.flush()` 强制先执行删除，并对 `tag_ids` 去重

---

## 调试流程（按顺序执行）

### 步骤 1：启动全部服务

```bash
cd /mnt/e/other/X-Lab/Hackthon/Hacathon_MVP
docker compose up -d --build
```

首次构建需要下载镜像和安装依赖，约 2-5 分钟。等待所有容器 healthy：

```bash
docker compose ps
# 所有服务 STATUS 应为 "Up (healthy)"
```

### 步骤 2：运行数据库迁移

```bash
make migrate
# 等价: docker compose run --rm api alembic upgrade head
```

验证迁移是否成功：

```bash
docker compose run --rm api alembic current
# 应输出: 0002 (head)
```

### 步骤 3：获取 JWT Token

```bash
# 注册新用户（已有账户就用 login）
curl -sk -X POST https://localhost/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"1234567890"}'
```

返回示例：
```json
{"access_token":"eyJ...","token_type":"bearer"}
```

把 token 存为 shell 变量方便后续：
```bash
TOKEN="eyJ..."   # 替换为实际 token
```

### 步骤 4：测试日程模块全部接口

#### 4.1 创建文件夹
```bash
curl -sk -X POST https://localhost/api/v1/schedule-folders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"学习计划"}'
```
→ 记录返回的 `"id"` 字段，后面用作 `FOLDER_ID`

#### 4.2 创建标签
```bash
curl -sk -X POST https://localhost/api/v1/schedule-tags \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"高数","color":"#4ecdc4"}'
```
→ 记录返回的 `"id"` 字段，后面用作 `TAG_ID`

#### 4.3 创建日程（注意替换真实 ID）
```bash
# ⚠️ 先把下面 FOLDER_ID 和 TAG_ID 替换成 4.1 和 4.2 返回的真实 UUID
curl -sk -X POST https://localhost/api/v1/schedules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "folder_id":"替换为真实FOLDER_ID",
    "title":"复习微积分",
    "description":"第三章课后习题",
    "starts_at":"2026-08-13T09:00:00+08:00",
    "ends_at":"2026-08-13T11:00:00+08:00",
    "tag_ids":["替换为真实TAG_ID"]
  }'
```
→ 记录返回的 `"id"` 字段，后面用作 `SCHEDULE_ID`

💡 **懒人一键版本**（用 shell 变量自动提取，不用手动复制 ID）：
```bash
# 创建文件夹并自动提取 ID
FOLDER_ID=$(curl -sk -X POST https://localhost/api/v1/schedule-folders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"学习计划"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 创建标签并自动提取 ID
TAG_ID=$(curl -sk -X POST https://localhost/api/v1/schedule-tags \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"高数","color":"#4ecdc4"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 创建日程
curl -sk -X POST https://localhost/api/v1/schedules \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"folder_id\":\"$FOLDER_ID\",\"title\":\"复习微积分\",\"description\":\"第三章课后习题\",\"starts_at\":\"2026-08-13T09:00:00+08:00\",\"ends_at\":\"2026-08-13T11:00:00+08:00\",\"tag_ids\":[\"$TAG_ID\"]}"
```

#### 4.4 标记日程为完成
```bash
curl -sk -X PUT https://localhost/api/v1/schedules/$SCHEDULE_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_completed":true}'
```

#### 4.5 查看统计（饼状图数据）
```bash
curl -sk "https://localhost/api/v1/schedules/stats?period=month" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

期望输出：
```json
{
  "period": "month",
  "total_completed": 1,
  "tag_counts": [
    {"tag_id": "<TAG_ID>", "tag_name": "高数", "tag_color": "#4ecdc4", "count": 1}
  ]
}
```

#### 4.6 测试其他端点
```bash
# 获取文件夹列表
curl -sk https://localhost/api/v1/schedule-folders -H "Authorization: Bearer $TOKEN"

# 获取标签列表
curl -sk https://localhost/api/v1/schedule-tags -H "Authorization: Bearer $TOKEN"

# 获取日程列表（可按条件过滤）
curl -sk "https://localhost/api/v1/schedules?is_completed=true" -H "Authorization: Bearer $TOKEN"

# 更新文件夹名
curl -sk -X PUT https://localhost/api/v1/schedule-folders/$FOLDER_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"新名称"}'

# 删除日程
curl -sk -X DELETE https://localhost/api/v1/schedules/$SCHEDULE_ID \
  -H "Authorization: Bearer $TOKEN" -w "\nHTTP %{http_code}\n"
```

---

## 调试技巧

### 实时查看日志
```bash
# 只看 API 服务日志
docker compose logs -f api

# 看所有日志
docker compose logs -f
```

### 进入容器调试
```bash
docker compose exec api bash
# 然后在容器内:
python -c "
from services.core.app.models import Schedule, ScheduleFolder, ScheduleTag
print('All models imported OK')
"
```

### 直接查数据库
```bash
docker compose exec postgres psql -U study -d study
```
在 psql 中：
```sql
\dt                              -- 列出所有表
\d schedules                     -- 查看 schedules 表结构
SELECT * FROM schedule_folders;  -- 查看文件夹数据
SELECT * FROM schedule_tags;     -- 查看标签数据
SELECT * FROM schedules;         -- 查看日程数据
```

### 使用 Swagger UI（强烈推荐）

浏览器打开 **http://localhost:80/docs** 或 **http://localhost:8000/docs**

1. 点击右上角 **Authorize** 🔒
2. 填入 `Bearer <token>` 或直接填 token（Swagger 会自动加 Bearer 前缀）
3. 展开任意日程接口，点 **Try it out** → **Execute**
4. 响应和错误信息直接显示在页面上

这是最方便的调试方式，不需要手写 curl。

---

## 常见报错速查

| 错误 | 原因 | 解决 |
|------|------|------|
| `required variable MINIO_ROOT_USER is missing` | 没有 `.env` 文件 | `cp .env.example .env` |
| `401 Unauthorized` | Token 过期或没传 | 重新登录获取 token |
| `409 Conflict: Folder name already exists` | 同名文件夹已存在 | 换一个 name |
| `422 Validation Error` | 请求格式不对 | 检查 `starts_at < ends_at`，时间格式 ISO 8601 |
| `relation "schedule_folders" does not exist` | 没跑迁移 | `make migrate` |
| `404 Folder not found` | folder_id 不属于当前用户 | 先 `GET /schedule-folders` 确认 ID |
| `400 ends_at must be after starts_at` | 结束时间早于或等于开始时间 | 调换时间，确保 ends_at 严格晚于 starts_at |
| `500 Internal Server Error`（更新带 tag_ids） | 标签关联唯一约束冲突 | 已修复，若再现查看 `docker compose logs api` |

---

## 停止与清理

```bash
# 停止所有服务
docker compose down

# 停止并删除数据卷（重置数据库）
docker compose down -v

# 重新构建（修改代码后）
docker compose up -d --build
```
