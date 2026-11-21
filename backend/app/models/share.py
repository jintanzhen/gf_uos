# -*- coding: utf-8 -*-
"""份额明细域（决议 D1/D2）：份额 = 会员名下 OrderType=FenE 的生效订单明细。"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class ShareDetail(TimestampMixin, Base):
    """一份份额 = 源系统一条 OrderDetail 的循环配送属性。

    remain_times = 源 OrderDetail.RemainShipTimes（D2 唯一剩余口径）。
    """

    __tablename__ = "share_detail"
    __table_args__ = (
        Index("uq_share_ext", "ext_detail_id", unique=True),
        Index("ix_share_member", "member_id"),
        Index("ix_share_remain", "remain_times"),
        Index("ix_share_status", "order_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ext_detail_id: Mapped[str] = mapped_column(String(36), comment="源 OrderDetail GUID")
    member_id: Mapped[int] = mapped_column()
    ext_order_id: Mapped[Optional[str]] = mapped_column(String(36), comment="源 OrderInfo GUID")
    share_type: Mapped[Optional[str]] = mapped_column(String(10), comment="shucai / doufu / douya")
    good_name: Mapped[Optional[str]] = mapped_column(String(200), comment="jstGood 商品名")
    total_cnt: Mapped[Optional[int]] = mapped_column(Integer, comment="LoopShipCount 总次数")
    shipped_cnt: Mapped[Optional[int]] = mapped_column(Integer, comment="LoopShipedTimes 已配次数")
    remain_times: Mapped[Optional[int]] = mapped_column(Integer, comment="RemainShipTimes 剩余次数")
    cycle_desc: Mapped[Optional[str]] = mapped_column(String(100), comment="LoopShipDescription 配送周期")
    start_ship_date: Mapped[Optional[date]] = mapped_column(Date)
    end_ship_date: Mapped[Optional[date]] = mapped_column(Date)
    order_status: Mapped[Optional[int]] = mapped_column(Integer, comment="源 OrderStatus")
    sui_status: Mapped[Optional[str]] = mapped_column(String(20), comment="源 SuiFenEStatus")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
