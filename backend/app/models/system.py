# -*- coding: utf-8 -*-
"""系统域：audit_log（只增）/ sync_log（F1-08 对账）/ spider_cursor（增量游标）。"""
import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin, utcnow


class AuditLog(Base):
    """操作审计（F5-03）：只增不改不删，唯一写入口见 app.core.audit。"""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_action_time", "action", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column()
    action: Mapped[str] = mapped_column(String(50), comment="access_denied / login_failed / export / ...")
    object_type: Mapped[Optional[str]] = mapped_column(String(50))
    object_id: Mapped[Optional[str]] = mapped_column(String(64))
    detail_json: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SyncLog(TimestampMixin, Base):
    """同步对账日志（F1-08）：diff_count>0 告警；失败游标不前移（BR-08）。"""

    __tablename__ = "sync_log"
    __table_args__ = (Index("ix_sync_type_time", "sync_type", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(20), comment="staff / member / order / share / binding")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="ok")
    total_source: Mapped[Optional[int]] = mapped_column(Integer)
    total_local: Mapped[Optional[int]] = mapped_column(Integer)
    diff_count: Mapped[Optional[int]] = mapped_column(Integer)
    detail_json: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)


class SpiderCursor(Base):
    """spider 增量游标：按源表记录 last_sync_time（ModifyDate > cursor）。"""

    __tablename__ = "spider_cursor"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_sync_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
