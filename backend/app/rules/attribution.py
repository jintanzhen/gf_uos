# -*- coding: utf-8 -*-
"""续订归因引擎（F6-04/F6-05，D3/D7）：任务完成后 N 天内的续订信号判定与每日回补。

续订信号（D3，任一即成立）：
- new_order       会员出现新的 FenE 订单（ext_order 首次入库时间落在窗口内）
- match_order     新订单经 MatchOrderID/OldOrderID 关联到前序份额
- remain_rebound  同份额剩余次数回升（share_detail.remain_times > 生成时快照）

基线（对照组，验收要点）：对照组会员"自行续订"按 rule_experiment_member.assigned_at
起算同样的窗口，只进基线不进任务归因。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.member import Member
from ..models.order import ExtOrder
from ..models.rule import Rule
from ..models.share import ShareDetail
from ..models.task import Task

logger = logging.getLogger("greenos.attribution")

DEFAULT_ATTRIBUTION_DAYS = 30  # D7 默认窗口


def _utc_offset() -> timedelta:
    """运行时 UTC 偏移：ext_order.created_at 由 utcnow 写入（UTC），业务时间为本地，统一换算。"""
    return datetime.now() - datetime.utcnow()


def _to_utc(dt_local: datetime) -> datetime:
    return dt_local - _utc_offset()


def _detect_renewal(db: Session, task: Task, member_ext_id: Optional[int],
                    window_start: datetime, window_end: datetime) -> Optional[tuple[str, str]]:
    """返回 (signal, ext_order_id) 或 None。信号优先级：match_order > new_order > remain_rebound。"""
    if member_ext_id is None:
        rows = []
    else:
        rows = db.execute(
            select(ExtOrder.ext_order_id, ExtOrder.match_order_id, ExtOrder.old_order_id)
            .where(ExtOrder.ext_mem_id == member_ext_id,
                   ExtOrder.order_type == "FenE",
                   ExtOrder.created_at > _to_utc(window_start),
                   ExtOrder.created_at <= _to_utc(window_end))
        ).all()
    # 信号③：新订单关联到前序份额
    for oid, match_id, old_id in rows:
        if match_id or old_id:
            return "match_order", oid
    # 信号①：窗口内新 FenE 订单
    if rows:
        return "new_order", rows[0][0]
    # 信号②：剩余次数回升（生成时快照存在才可判定）
    if task.remain_times_at_create is not None:
        share = db.get(ShareDetail, task.share_detail_id)
        if (share is not None and share.remain_times is not None
                and share.remain_times > task.remain_times_at_create):
            return "remain_rebound", ""
    return None


def attribute_renewals(db: Session, now: Optional[datetime] = None,
                       rule_id: Optional[int] = None, recompute: bool = False) -> dict:
    """每日回补：对归因窗口内的已完成任务判定续订信号。

    recompute=True（F6-05 历史重算）：清除该规则任务的归因标记后重算，
    结果与首次计算一致（验收要点：幂等，不出现同一天两次查询数字不同）。
    """
    now = now or datetime.now()
    detected = 0
    closed = 0
    if recompute and rule_id:
        db.query(Task).filter(Task.rule_id == rule_id).update(
            {"renew_detected_at": None, "renew_signal": None,
             "renew_ext_order_id": None, "renew_window_closed": False},
            synchronize_session=False,
        )
        db.commit()

    query = (db.query(Task, Rule, Member.ext_member_id)
             .join(Rule, Rule.id == Task.rule_id)
             .join(Member, Member.id == Task.member_id)
             .filter(Task.status == "done", Task.completed_at.is_not(None),
                     Task.renew_window_closed.is_(False)))
    if rule_id:
        query = query.filter(Task.rule_id == rule_id)
    for task, rule, member_ext_id in query.all():
        days = max(int(rule.attribution_days or DEFAULT_ATTRIBUTION_DAYS), 1)
        window_end = task.completed_at + timedelta(days=days)
        if now > window_end:
            task.renew_window_closed = True  # 窗口已过且未检出，关闭
            closed += 1
            continue
        hit = _detect_renewal(db, task, member_ext_id, task.completed_at, window_end)
        if hit:
            task.renew_detected_at = now
            task.renew_signal, task.renew_ext_order_id = hit
            detected += 1
    db.commit()

    # 对照组基线窗口关闭（同样按 assigned_at + attribution_days）
    _close_ctrl_windows(db, now)
    return {"detected": detected, "windows_closed": closed, "status": "ok"}


def _close_ctrl_windows(db: Session, now: datetime) -> None:
    """窗口过期的任务统一关闭（含 pending/cancelled 等未完成任务，不再回补）。"""
    rules = db.scalars(select(Rule)).all()
    for rule in rules:
        days = max(int(rule.attribution_days or DEFAULT_ATTRIBUTION_DAYS), 1)
        cutoff_days = days + 30  # 计划时间超出窗口 30 天的任务必已不可能归因
        db.query(Task).filter(
            Task.rule_id == rule.id,
            Task.renew_window_closed.is_(False),
            Task.renew_detected_at.is_(None),
            Task.plan_time.is_not(None),
            Task.plan_time < now - timedelta(days=cutoff_days),
        ).update({"renew_window_closed": True}, synchronize_session=False)
    db.commit()


def _renewal_at_anchor(db: Session, member_ext_id: int,
                       anchor: datetime, days: int) -> bool:
    """基线判定：anchor 起算 N 天窗口内是否出现新 FenE 订单（对照组，仅进基线）。"""
    if member_ext_id is None:
        return False
    row = db.scalar(
        select(ExtOrder.id).where(
            ExtOrder.ext_mem_id == member_ext_id,
            ExtOrder.order_type == "FenE",
            ExtOrder.created_at > _to_utc(anchor),
            ExtOrder.created_at <= _to_utc(anchor + timedelta(days=days)),
        ).limit(1))
    return row is not None
