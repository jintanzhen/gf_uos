# -*- coding: utf-8 -*-
"""数据库引擎与会话：SQLite(WAL) 起步，SQLAlchemy 2.x 保持 PG 兼容（ADR-2）。"""
import datetime as dt
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def _make_engine():
    kwargs: dict = {"future": True}
    if settings.database_url.startswith("sqlite"):
        # FastAPI 多线程访问需要放宽同线程检查
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.database_url, **kwargs)


engine = _make_engine()

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=OFF")  # 逻辑外键约定（架构 §3.2）
        cur.close()


def ensure_sqlite_dir() -> None:
    """确保 SQLite 文件所在目录存在（data/ 自动创建并 gitignore）。"""
    if not settings.database_url.startswith("sqlite"):
        return
    path = settings.database_url.split("///", 1)[-1]
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def utcnow() -> dt.datetime:
    """UTC naive 时间，SQLite/PG 通用存储口径。"""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """全部业务表的 created_at / updated_at（UTC）。"""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
