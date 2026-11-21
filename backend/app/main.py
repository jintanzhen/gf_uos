# -*- coding: utf-8 -*-
"""Green-OS 后端入口：FastAPI 装配 + APScheduler 内嵌启动（ADR-1）。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.admin import router as admin_router
from .api.auth import router as auth_router
from .api.health import router as health_router
from .api.members import router as members_router
from .api.pool import router as pool_router
from .api.reports import router as reports_router
from .api.rules import router as rules_router
from .api.tasks import router as tasks_router
from .core.config import settings
from .core.db import ensure_sqlite_dir
from .scheduler.jobs import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("greenos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_sqlite_dir()
    start_scheduler()
    logger.info("%s v%s started", settings.app_name, settings.app_version)
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(members_router, prefix="/api")
app.include_router(rules_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(pool_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
