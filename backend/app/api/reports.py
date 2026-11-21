# -*- coding: utf-8 -*-
"""效果看板 API（模块六）：任务总览 / 实验效果对比（核心）/ 规则排行榜 / 客服绩效 / 历史重算。

口径（F6-04/D7）：任务完成后 N 天（规则级 attribution_days）内的续订归因于本任务；
对照组自行续订只进基线（F6-05 _renewal_at_anchor，anchor=分流落库时间）。
验收要点：历史重算幂等——同一天两次查询数字一致（除非有新数据进入）。
"""
from datetime import datetime, timedelta
from math import sqrt
from statistics import NormalDist
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import require_ops
from ..models.member import Member
from ..models.operator import Operator
from ..models.order import ExtOrder
from ..models.rule import Rule, RuleExperimentMember
from ..models.task import Task, TouchRecord
from ..rules.attribution import _renewal_at_anchor, attribute_renewals

router = APIRouter(prefix="/ops/reports", tags=["reports"])


def _two_proportion_p(x1: int, n1: int, x2: int, n2: int) -> Optional[float]:
    """双比例 z 检验（F6-03 简化版）：exp vs ctrl 续订率差异显著性 p 值。"""
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    return 2 * (1 - NormalDist().cdf(abs(z)))


def _task_filter(db: Session, rule_id=None, cs_id=None, date_from=None, date_to=None):
    query = db.query(Task)
    if rule_id:
        query = query.filter(Task.rule_id == rule_id)
    if cs_id:
        query = query.filter(Task.cs_id == cs_id)
    if date_from:
        query = query.filter(Task.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        query = query.filter(Task.created_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
    return query


@router.get("/overview", summary="F6-01 任务总览（按规则/客服/时间筛选）")
def overview(rule_id: Optional[int] = Query(None), cs_id: Optional[int] = Query(None),
             date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
             operator: Operator = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    tasks = _task_filter(db, rule_id, cs_id, date_from, date_to).all()
    now = datetime.now()
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    pending = sum(1 for t in tasks if t.status == "pending")
    cancelled = sum(1 for t in tasks if t.status == "cancelled")
    expired = sum(1 for t in tasks if t.status == "expired")
    overdue = sum(1 for t in tasks if t.status == "pending" and t.plan_time and t.plan_time < now)
    latencies = [t2.latency_seconds for t2 in db.query(TouchRecord).filter(
        TouchRecord.task_id.in_([t.id for t in tasks] or [0]),
        TouchRecord.latency_seconds.is_not(None)).all()] if tasks else []
    distribution: dict[str, int] = {}
    for t in tasks:
        if t.status == "done":
            distribution[t.result or "unknown"] = distribution.get(t.result or "unknown", 0) + 1
    by_day: dict[str, dict[str, int]] = {}
    for t in tasks:
        day = t.created_at.date().isoformat()
        slot = by_day.setdefault(day, {"generated": 0, "done": 0})
        slot["generated"] += 1
        if t.status == "done":
            slot["done"] += 1
    return {
        "generated": total, "done": done, "pending": pending,
        "cancelled": cancelled, "expired": expired, "overdue": overdue,
        "completion_rate": round(done / total, 4) if total else None,
        "avg_latency_seconds": (round(sum(latencies) / len(latencies), 1)
                                if latencies else None),
        "result_distribution": distribution,
        "by_day": [{"date": k, **v} for k, v in sorted(by_day.items())],
    }

@router.get("/experiment/{rule_id}", summary="F6-02 实验效果对比（核心）：实验组 vs 对照组")
def experiment(rule_id: int, operator: Operator = Depends(require_ops),
               db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="规则不存在")
    days = max(int(rule.attribution_days or 30), 1)
    now = datetime.now()

    tasks = db.query(Task).filter(Task.rule_id == rule_id).all()
    done_tasks = [t for t in tasks if t.status == "done"]
    renewals = [t for t in tasks if t.renew_detected_at is not None]
    done_renewals = [t for t in renewals if t.status == "done"]

    exp_ids = [t.id for t in tasks]
    exp = {
        "generated": len(tasks), "done": len(done_tasks),
        "contact_rate": round(len(done_tasks) / len(tasks), 4) if tasks else None,
        "renewals": len(renewals), "renewals_of_done": len(done_renewals),
        "renew_rate_of_done": (round(len(done_renewals) / len(done_tasks), 4)
                               if done_tasks else None),
        "renew_rate_of_generated": (round(len(renewals) / len(tasks), 4)
                                    if tasks else None),
        "signal_distribution": _signal_dist(renewals),
    }

    # 对照组基线：分流落库时间起算同长窗口，仅计自行续订（验收要点）
    ctrl_rows = db.execute(
        select(RuleExperimentMember.member_id, RuleExperimentMember.assigned_at, Member.ext_member_id)
        .join(Member, Member.id == RuleExperimentMember.member_id)
        .where(RuleExperimentMember.rule_id == rule_id,
               RuleExperimentMember.grp == "ctrl")).all()
    ctrl_renewals = sum(1 for _mid, anchor, ext_id in ctrl_rows
                        if _renewal_at_anchor(db, ext_id, anchor, days))
    n_ctrl = len(ctrl_rows)
    ctrl = {"members": n_ctrl, "renewals": ctrl_renewals,
            "renew_rate": round(ctrl_renewals / n_ctrl, 4) if n_ctrl else None}

    rate_exp = exp["renew_rate_of_done"]
    rate_ctrl = ctrl["renew_rate"]
    diff = (round(rate_exp - rate_ctrl, 4)
            if rate_exp is not None and rate_ctrl is not None else None)
    lift = (round((rate_exp - rate_ctrl) / rate_ctrl, 4)
            if diff is not None and rate_ctrl else None)
    p_value = _two_proportion_p(len(done_renewals), len(done_tasks),
                                ctrl_renewals, n_ctrl)
    reliable = len(done_tasks) >= 30 and n_ctrl >= 30  # 样本量约定（F3-04 同口径）
    return {
        "rule": {"id": rule.id, "name": rule.name,
                 "attribution_days": days,
                 "experiment_ratio": rule.experiment_ratio},
        "exp": exp, "ctrl": ctrl,
        "diff": diff, "relative_lift": lift,
        "p_value": round(p_value, 4) if p_value is not None else None,
        "conclusion_reliable": reliable,
        "warning": None if reliable else "样本不足 30，结论不可信（F6-03）",
    }


def _signal_dist(tasks) -> dict:
    dist: dict[str, int] = {}
    for t in tasks:
        dist[t.renew_signal or "unknown"] = dist.get(t.renew_signal or "unknown", 0) + 1
    return dist


@router.get("/rules-ranking", summary="F6-06 规则排行榜（按相对提升排序）")
def rules_ranking(operator: Operator = Depends(require_ops),
                  db: Session = Depends(get_db)) -> list[dict]:
    rules = db.scalars(select(Rule).order_by(Rule.priority.desc())).all()
    out = []
    for rule in rules:
        exp = experiment(rule.id, operator, db)  # 复用对比口径
        out.append({
            "rule_id": rule.id, "rule_name": rule.name, "status": rule.status,
            "exp": exp["exp"], "ctrl": exp["ctrl"],
            "diff": exp["diff"], "relative_lift": exp["relative_lift"],
            "p_value": exp["p_value"], "conclusion_reliable": exp["conclusion_reliable"],
        })
    out.sort(key=lambda x: (x["relative_lift"] is not None, x["relative_lift"] or 0), reverse=True)
    return out


@router.get("/cs-performance", summary="F6-07 客服绩效")
def cs_performance(date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                   operator: Operator = Depends(require_ops),
                   db: Session = Depends(get_db)) -> list[dict]:
    operators = db.scalars(select(Operator).where(Operator.status == "active")).all()
    now = datetime.now()
    out = []
    for op in operators:
        tasks = _task_filter(db, cs_id=op.id, date_from=date_from, date_to=date_to).all()
        if not tasks:
            continue
        done = [t for t in tasks if t.status == "done"]
        on_time = sum(1 for t in done if t.plan_time and t.completed_at
                      and t.completed_at <= t.plan_time + timedelta(days=1))
        renewals = sum(1 for t in tasks if t.renew_detected_at is not None)
        latencies = [t2.latency_seconds for t2 in db.query(TouchRecord).filter(
            TouchRecord.task_id.in_([t.id for t in done] or [0]),
            TouchRecord.latency_seconds.is_not(None)).all()] if done else []
        out.append({
            "cs_id": op.id, "cs_name": op.name,
            "generated": len(tasks), "done": len(done),
            "completion_rate": round(len(done) / len(tasks), 4),
            "on_time_rate": round(on_time / len(done), 4) if done else None,
            "avg_latency_seconds": (round(sum(latencies) / len(latencies), 1)
                                    if latencies else None),
            "attributed_renewals": renewals,
        })
    out.sort(key=lambda x: x["done"], reverse=True)
    return out


class RecomputeIn(BaseModel):
    rule_id: int


@router.post("/recompute", summary="F6-05 历史重算（清除归因标记后重跑，结果幂等）")
def recompute(body: RecomputeIn, operator: Operator = Depends(require_ops),
              db: Session = Depends(get_db)) -> dict:
    if db.get(Rule, body.rule_id) is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="规则不存在")
    return attribute_renewals(db, rule_id=body.rule_id, recompute=True)
