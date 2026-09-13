import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import EventKind, TaskStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    kind: EventKind = EventKind.EVENT

    @model_validator(mode="after")
    def validate_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class EventOut(EventCreate, ORMModel):
    id: uuid.UUID
    source: str


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = None
    due_at: datetime | None = None


class TaskOut(TaskCreate, ORMModel):
    id: uuid.UUID
    status: TaskStatus
    source: str


class FocusStart(BaseModel):
    planned_minutes: int = Field(default=25, ge=1, le=180)


class FocusOut(ORMModel):
    id: uuid.UUID
    planned_minutes: int
    started_at: datetime
    finished_at: datetime | None


class BalanceOut(BaseModel):
    balance: int


# ──────────────── Schedule Folder Schemas ────────────────


class ScheduleFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ScheduleFolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ScheduleFolderOut(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


# ──────────────── Schedule Tag Schemas ────────────────


class ScheduleTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class ScheduleTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class ScheduleTagOut(ORMModel):
    id: uuid.UUID
    name: str
    color: str | None
    created_at: datetime


# ──────────────── Schedule (日程) Schemas ────────────────


class ScheduleCreate(BaseModel):
    folder_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    tag_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def validate_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ScheduleUpdate(BaseModel):
    folder_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_completed: bool | None = None
    tag_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class ScheduleOut(ORMModel):
    id: uuid.UUID
    folder_id: uuid.UUID | None
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    is_completed: bool
    tags: list[ScheduleTagOut] = []
    created_at: datetime


# ──────────────── Schedule Stats Schemas ────────────────


class TagCountItem(BaseModel):
    tag_id: uuid.UUID | None = None  # None = 无标签
    tag_name: str
    tag_color: str | None = None
    count: int


class ScheduleStatsOut(BaseModel):
    period: str  # day / week / month / year
    total_completed: int
    tag_counts: list[TagCountItem]

