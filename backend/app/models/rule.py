# -*- coding: utf-8 -*-
"""规则域：rule / rule_experiment_member（BR-11 分流落库制）/ rule_scan_log（F3-06）。"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, TimestampMixin


class Rule(TimestampMixin, Base):
    """规则 = 命中条件 + 执行时间 + 模板 + 频控 + 实验设置 + 有效期 + 归因窗口（PRD 5.4.1）。"""

    __tablename__ = "rule"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    conditions_json: Mapped[str] = mapped_column(Text, comment="两层嵌套条件树（ADR-5）")
    exec_time: Mapped[str] = mapped_column(String(5), comment="扫描时刻，如 09:30")
    freq: Mapped[str] = mapped_column(String(10), default="daily", comment="daily / weekly")
    weekdays: Mapped[Optional[str]] = mapped_column(String(20), comment="weekly 时：逗号分隔 0-6")
    plan_time: Mapped[str] = mapped_column(String(5), comment="任务计划时刻，如 10:00")
    template: Mapped[str] = mapped_column(Text)
    benefit_text: Mapped[Optional[str]] = mapped_column(String(200), comment="{续订权益} 变量的静态文本（附录 C）")
    freq_n_days: Mapped[int] = mapped_column(Integer, default=7, comment="BR-04：N 天窗口")
    freq_m_times: Mapped[int] = mapped_column(Integer, default=2, comment="BR-04：窗口内上限（≤4 硬上限）")
    experiment_enabled: Mapped[bool] = mapped_column(default=True)
    experiment_ratio: Mapped[int] = mapped_column(Integer, default=20, comment="对照组比例 10~50（D8）")
    attribution_days: Mapped[int] = mapped_column(Integer, default=30, comment="归因窗口（D7）")
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="BR-09 多规则互斥时取最高")
    status: Mapped[str] = mapped_column(String(10), default="enabled", comment="enabled / disabled / expired")
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    created_by: Mapped[Optional[int]] = mapped_column()


class RuleExperimentMember(TimestampMixin, Base):
    """分组持久事实（ADR-3）：首次计算落库后只读，保证 BR-11 分组永不变更。"""

    __tablename__ = "rule_experiment_member"
    __table_args__ = (
        Index("uq_experiment_rule_member", "rule_id", "member_id", unique=True),
        Index("ix_experiment_member", "member_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column()
    member_id: Mapped[int] = mapped_column()
    grp: Mapped[str] = mapped_column(String(4), comment="exp / ctrl")
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class RuleScanLog(TimestampMixin, Base):
    """每轮扫描执行日志（F3-06），跳过分类齐全，供排障与对账。"""

    __tablename__ = "rule_scan_log"
    __table_args__ = (Index("ix_scan_rule_time", "rule_id", "scan_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column()
    scan_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    exp_generated: Mapped[int] = mapped_column(Integer, default=0)
    ctrl_skipped: Mapped[int] = mapped_column(Integer, default=0)
    freq_skipped: Mapped[int] = mapped_column(Integer, default=0)
    blacklist_skipped: Mapped[int] = mapped_column(Integer, default=0)
    dedup_skipped: Mapped[int] = mapped_column(Integer, default=0)
    conflict_skipped: Mapped[int] = mapped_column(Integer, default=0, comment="BR-09 互斥：更高优先级规则已占用")
    status: Mapped[str] = mapped_column(String(10), default="ok")
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
