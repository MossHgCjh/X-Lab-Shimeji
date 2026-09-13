from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import router
from .config import get_settings
from .db import SessionLocal


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="Study Platform API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health/live", tags=["health"])
async def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready():
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}

