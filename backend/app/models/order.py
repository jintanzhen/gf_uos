# -*- coding: utf-8 -*-
"""ext_order：源系统订单暂存表（sync 域自用），为 share_detail 的 FenE 判定与状态回填服务。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class ExtOrder(TimestampMixin, Base):
    """OrderInfo 镜像的最小字段集（仅同步管线使用，业务查询走 share_detail）。"""

    __tablename__ = "ext_order"
    __table_args__ = (
        Index("uq_ext_order", "ext_order_id", unique=True),
        Index("ix_ext_order_mem", "ext_mem_id"),
        Index("ix_ext_order_modify", "modify_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ext_order_id: Mapped[str] = mapped_column(String(36), comment="源 OrderInfo GUID")
    ext_mem_id: Mapped[Optional[int]] = mapped_column(comment="源 MemID")
    order_type: Mapped[Optional[str]] = mapped_column(String(20), comment="FenE / SanDan / HunHe")
    order_status: Mapped[Optional[int]] = mapped_column(Integer, comment="1待审/2已审/3完结/4暂停/5异常/6仅展示/0删除")
    sui_status: Mapped[Optional[str]] = mapped_column(String(20), comment="SuiFenEStatus 匹配状态机")
    modify_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # ---- M3 归因信号字段（F6-05：新 FenE 订单 / MatchOrderID 关联）----
    pay_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="源 pay_time")
    total_price: Mapped[Optional[float]] = mapped_column(Float, comment="源 TotalPrice")
    match_order_id: Mapped[Optional[str]] = mapped_column(String(36), comment="源 MatchOrderID")
    old_order_id: Mapped[Optional[str]] = mapped_column(String(36), comment="源 OldOrderID")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
