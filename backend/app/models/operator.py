# -*- coding: utf-8 -*-
"""人员与归属域：operator / cs_member_binding（决议 R1：同会员仅一个专属客服）。"""
from typing import Optional

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class Operator(TimestampMixin, Base):
    """客服/运营/超管统一人员表（role 区分）。客服由源系统 StaffInfo 同步（ext_cs_id），本地账号为空。"""

    __tablename__ = "operator"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ext_cs_id: Mapped[Optional[int]] = mapped_column(unique=True, comment="源 StaffInfo 对应 ID，本地运营账号为空")
    name: Mapped[str] = mapped_column(String(50), unique=True, comment="登录名（兼显示名）")
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    qrcode_url: Mapped[Optional[str]] = mapped_column(String(500), comment="企微二维码，模板变量来源")
    role: Mapped[str] = mapped_column(String(10), comment="cs / ops / admin")
    status: Mapped[str] = mapped_column(String(10), default="active", comment="active / left")
    password_hash: Mapped[str] = mapped_column(String(128))


class CsMemberBinding(TimestampMixin, Base):
    """会员-客服归属（BR-01 任务固化前的归属事实源）。

    R1：同一会员同一时刻仅一条 is_current=1 —— 由迁移内触发器强制（SQLite 无 partial index），
    同步发现重复归属时告警人工处理，不静默建多条。
    """

    __tablename__ = "cs_member_binding"
    __table_args__ = (
        Index("ix_binding_member_current", "member_id", "is_current"),
        Index("ix_binding_cs", "cs_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cs_id: Mapped[int] = mapped_column(comment="operator.id")
    member_id: Mapped[int] = mapped_column(comment="member.id")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="StaffInfo")
