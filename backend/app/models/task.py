# -*- coding: utf-8 -*-
"""任务域：task（BR-03 唯一索引 + R4 公共池）/ task_state_log（BR-07）/ touch_record（F5-02）。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class Task(TimestampMixin, Base):
    """任务主体 = 会员 + 份额明细（BR-13）。cs_id 生成时固化（BR-01）。

    uq_task 四字段唯一索引是 BR-03 去重与幂等（ADR-4 INSERT OR IGNORE）的根基。
    pool=True：无归属客服的公共池任务（R4，cs_id 为空），运营认领后写入 cs_id。
    """

    __tablename__ = "task"
    __table_args__ = (
        Index("uq_task", "member_id", "rule_id", "share_detail_id", "cycle_key", unique=True),
        Index("ix_task_cs_status_plan", "cs_id", "status", "plan_time"),
        Index("ix_task_pool_status", "pool", "status"),
        Index("ix_task_rule", "rule_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column()
    cs_id: Mapped[Optional[int]] = mapped_column(comment="BR-01 生成时固化；公共池任务为空")
    member_id: Mapped[int] = mapped_column()
    share_detail_id: Mapped[int] = mapped_column()
    plan_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cycle_key: Mapped[str] = mapped_column(String(20), comment="周期去重键，如 2026-03-05")
    status: Mapped[str] = mapped_column(String(10), default="pending", comment="pending/done/cancelled/expired")
    result: Mapped[Optional[str]] = mapped_column(String(10), comment="六枚举（F4-06）")
    remark: Mapped[Optional[str]] = mapped_column(Text, comment="选『其他』必填（D11）")
    copied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="复制留痕（F4-05）")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expire_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="D4：超过即自动过期")
    pool: Mapped[bool] = mapped_column(Boolean, default=False)
    # ---- M3 归因（F6-04/F6-05，D3/D7）----
    remain_times_at_create: Mapped[Optional[int]] = mapped_column(
        Integer, comment="生成时的剩余次数快照，信号②『剩余次数回升』的基线")
    renew_detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="归因续订检出时间（每日回补写入）")
    renew_signal: Mapped[Optional[str]] = mapped_column(
        String(20), comment="new_order 新FenE订单 / remain_rebound 剩余次数回升 / match_order MatchOrderID关联")
    renew_ext_order_id: Mapped[Optional[str]] = mapped_column(String(36), comment="归因到的源订单 GUID")
    renew_window_closed: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="归因窗口已结束且未检出续订（避免重复扫描）")


class TaskStateLog(TimestampMixin, Base):
    """任务状态变更日志（F5-01/BR-07），单向状态机的审计依据（BR-05）。"""

    __tablename__ = "task_state_log"
    __table_args__ = (Index("ix_state_task", "task_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column()
    from_status: Mapped[Optional[str]] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    operator_id: Mapped[Optional[int]] = mapped_column()
    reason: Mapped[Optional[str]] = mapped_column(String(200))


class TouchRecord(TimestampMixin, Base):
    """触达记录（F5-02）：完成即生成，含内容快照与耗时，归因查询的主表。"""

    __tablename__ = "touch_record"
    __table_args__ = (
        Index("ix_touch_member_time", "member_id", "completed_at"),
        Index("ix_touch_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column()
    member_id: Mapped[int] = mapped_column()
    cs_id: Mapped[Optional[int]] = mapped_column()
    content_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[Optional[str]] = mapped_column(String(10))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    latency_seconds: Mapped[Optional[int]] = mapped_column(Integer, comment="生成→完成耗时")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
