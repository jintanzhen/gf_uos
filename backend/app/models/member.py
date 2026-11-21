# -*- coding: utf-8 -*-
"""会员域：member / tag / blacklist。手机号仅匹配用，不作为主键（D15）。"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class Member(TimestampMixin, Base):
    __tablename__ = "member"
    __table_args__ = (Index("uq_member_ext", "ext_member_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ext_member_id: Mapped[int] = mapped_column(comment="源 memberinfo.MemID，唯一关联键")
    nickname: Mapped[Optional[str]] = mapped_column(String(100))
    real_name: Mapped[Optional[str]] = mapped_column(String(100))
    mobile: Mapped[Optional[str]] = mapped_column(String(20), comment="匹配用，脱敏展示")
    another_phone: Mapped[Optional[str]] = mapped_column(String(20))
    staff_name: Mapped[Optional[str]] = mapped_column(
        String(100), comment="源 memberinfo.Staff 负责员工姓名，客服归属主口径", index=True)
    register_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, comment="源系统字段快照")


class Tag(TimestampMixin, Base):
    """会员标签：sys=系统自动（F2-03），manual=人工（F2-04）。"""

    __tablename__ = "tag"
    __table_args__ = (Index("ix_tag_member_key", "member_id", "tag_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column()
    tag_type: Mapped[str] = mapped_column(String(10), comment="sys / manual")
    tag_key: Mapped[str] = mapped_column(String(50))
    tag_value: Mapped[Optional[str]] = mapped_column(String(200))
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="如『勿扰至5月』")
    created_by: Mapped[Optional[int]] = mapped_column()


class Blacklist(TimestampMixin, Base):
    """黑名单/免打扰（BR-02）：活跃记录不生成任何任务；在途任务自动取消。"""

    __tablename__ = "member_blacklist"
    __table_args__ = (Index("uq_blacklist_member", "member_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="解除免打扰=置 False，保留历史")
    until_date: Mapped[Optional[date]] = mapped_column(Date, comment="免打扰截止日，空=永久")
    reason: Mapped[Optional[str]] = mapped_column(String(200))
    created_by: Mapped[Optional[int]] = mapped_column()
