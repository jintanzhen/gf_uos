# -*- coding: utf-8 -*-
"""规则管理 API（F3-01/03/04/06/07，运营端）：CRUD/启停/复制/命中预览/扫描日志。

校验（BR-04/D8/PRD 5.4.1）：freq_n_days>=7、freq_m_times<=4、
experiment_ratio 10~50、exec_time/plan_time HH:MM、条件树两层嵌套合法。
规则变更全部写审计（F5-03）。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.db import get_db
from ..core.deps import require_ops
from ..models.operator import Operator
from ..models.rule import Rule, RuleScanLog
from ..rules.evaluator import ConditionError, validate_tree
from ..rules.renderer import VARIABLES
from ..rules.scanner import preview_hits

router = APIRouter(prefix="/ops/rules", tags=["rules"])


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    conditions: dict
    exec_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    freq: str = Field(pattern="^(daily|weekly)$")
    weekdays: Optional[str] = None
    plan_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    template: str = Field(min_length=1)
    benefit_text: Optional[str] = Field(default=None, max_length=200)
    freq_n_days: int = Field(default=7, ge=7, le=365)
    freq_m_times: int = Field(default=2, ge=1, le=4)
    experiment_enabled: bool = True
    experiment_ratio: int = Field(default=20, ge=10, le=50)
    attribution_days: int = Field(default=30, ge=1, le=365)
    priority: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


def _check_times(rule_in: RuleIn) -> None:
    for t in (rule_in.exec_time, rule_in.plan_time):
        try:
            datetime.strptime(t, "%H:%M")
        except ValueError:
            raise HTTPException(status_code=422, detail=f"时间格式非法: {t}")
    if rule_in.freq == "weekly":
        ws = [w for w in (rule_in.weekdays or "").split(",") if w.strip()]
        if not ws or not all(w.strip().isdigit() and 0 <= int(w) <= 6 for w in ws):
            raise HTTPException(status_code=422, detail="weekly 需提供 weekdays（0-6 逗号分隔）")
    # 模板变量合法性（附录 C）
    import re
    used = set(re.findall(r"\{([^{}]+)\}", rule_in.template))
    unknown = used - set(VARIABLES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"模板含未支持变量: {sorted(unknown)}")


def _apply(rule: Rule, rule_in: RuleIn, operator_id: int) -> Rule:
    rule.name = rule_in.name
    rule.conditions_json = __import__("json").dumps(rule_in.conditions, ensure_ascii=False)
    rule.exec_time = rule_in.exec_time
    rule.freq = rule_in.freq
    rule.weekdays = rule_in.weekdays
    rule.plan_time = rule_in.plan_time
    rule.template = rule_in.template
    rule.benefit_text = rule_in.benefit_text
    rule.freq_n_days = rule_in.freq_n_days
    rule.freq_m_times = rule_in.freq_m_times
    rule.experiment_enabled = rule_in.experiment_enabled
    rule.experiment_ratio = rule_in.experiment_ratio
    rule.attribution_days = rule_in.attribution_days
    rule.priority = rule_in.priority
    rule.start_date = rule_in.start_date
    rule.end_date = rule_in.end_date
    rule.created_by = operator_id
    return rule


def _rule_out(rule: Rule) -> dict:
    import json as _json
    return {
        "id": rule.id, "name": rule.name,
        "conditions": _json.loads(rule.conditions_json),
        "exec_time": rule.exec_time, "freq": rule.freq, "weekdays": rule.weekdays,
        "plan_time": rule.plan_time, "template": rule.template,
        "benefit_text": rule.benefit_text,
        "freq_n_days": rule.freq_n_days, "freq_m_times": rule.freq_m_times,
        "experiment_enabled": rule.experiment_enabled,
        "experiment_ratio": rule.experiment_ratio,
        "attribution_days": rule.attribution_days, "priority": rule.priority,
        "status": rule.status, "start_date": rule.start_date,
        "end_date": rule.end_date, "updated_at": rule.updated_at,
    }

@router.post("", summary="创建规则（保存即生效）")
def create_rule(rule_in: RuleIn, request: Request, operator: Operator = Depends(require_ops),
                db: Session = Depends(get_db)) -> dict:
    try:
        validate_tree(rule_in.conditions)
    except ConditionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _check_times(rule_in)
    rule = _apply(Rule(status="enabled"), rule_in, operator.id)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    write_audit(db, actor_id=operator.id, action="rule_created",
                object_type="rule", object_id=str(rule.id),
                detail={"name": rule.name}, ip=request.client.host if request.client else None)
    return _rule_out(rule)


@router.get("", summary="规则列表")
def list_rules(status: Optional[str] = Query(None), search: Optional[str] = Query(None, max_length=50),
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               operator: Operator = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    query = select(Rule)
    if status:
        query = query.where(Rule.status == status)
    if search:
        query = query.where(Rule.name.like(f"%{search}%"))
    total = db.execute(select(__import__("sqlalchemy").func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(Rule.priority.desc(), Rule.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "items": [_rule_out(r) for r in rows]}


@router.get("/{rule_id}", summary="规则详情")
def get_rule(rule_id: int, operator: Operator = Depends(require_ops),
             db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return _rule_out(rule)


@router.put("/{rule_id}", summary="更新规则")
def update_rule(rule_id: int, rule_in: RuleIn, request: Request,
                operator: Operator = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    try:
        validate_tree(rule_in.conditions)
    except ConditionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _check_times(rule_in)
    _apply(rule, rule_in, operator.id)
    db.commit()
    write_audit(db, actor_id=operator.id, action="rule_updated",
                object_type="rule", object_id=str(rule.id),
                ip=request.client.host if request.client else None)
    return _rule_out(rule)


@router.post("/{rule_id}/toggle", summary="启用/停用规则")
def toggle_rule(rule_id: int, request: Request, operator: Operator = Depends(require_ops),
                db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    rule.status = "disabled" if rule.status == "enabled" else "enabled"
    db.commit()
    write_audit(db, actor_id=operator.id, action="rule_toggled",
                object_type="rule", object_id=str(rule.id),
                detail={"status": rule.status}, ip=request.client.host if request.client else None)
    return _rule_out(rule)


@router.post("/{rule_id}/duplicate", summary="复制规则")
def duplicate_rule(rule_id: int, request: Request, operator: Operator = Depends(require_ops),
                   db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    copy = Rule(status="disabled", created_by=operator.id)
    for col in Rule.__table__.columns:
        if col.name in ("id", "created_at", "updated_at", "status", "created_by"):
            continue
        setattr(copy, col.name, getattr(rule, col.name))
    copy.name = f"{rule.name}(副本)"
    db.add(copy)
    db.commit()
    db.refresh(copy)
    write_audit(db, actor_id=operator.id, action="rule_duplicated",
                object_type="rule", object_id=str(copy.id),
                ip=request.client.host if request.client else None)
    return _rule_out(copy)


@router.delete("/{rule_id}", summary="删除规则（任务保留，BR-01 固化不受影响）")
def delete_rule(rule_id: int, request: Request, operator: Operator = Depends(require_ops),
                db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    db.delete(rule)
    db.commit()
    write_audit(db, actor_id=operator.id, action="rule_deleted",
                object_type="rule", object_id=str(rule_id),
                ip=request.client.host if request.client else None)
    return {"deleted": rule_id}


@router.post("/{rule_id}/preview", summary="命中预览/试跑（不落库）")
def preview_rule(rule_id: int, operator: Operator = Depends(require_ops),
                 db: Session = Depends(get_db)) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    try:
        return preview_hits(db, rule)
    except ConditionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{rule_id}/run-scan", summary="手动触发该规则扫描（BR-03 去重保证幂等）")
def manual_scan(rule_id: int, request: Request, operator: Operator = Depends(require_ops),
                db: Session = Depends(get_db)) -> dict:
    from ..rules.scanner import run_scan

    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    stats = run_scan(db, rule)
    write_audit(db, actor_id=operator.id, action="rule_manual_scan",
                object_type="rule", object_id=str(rule.id),
                detail=stats, ip=request.client.host if request.client else None)
    return stats


@router.get("/{rule_id}/scan-logs", summary="扫描执行日志（F3-06）")
def rule_scan_logs(rule_id: int, limit: int = Query(20, ge=1, le=100),
                   operator: Operator = Depends(require_ops),
                   db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(RuleScanLog).where(RuleScanLog.rule_id == rule_id)
                      .order_by(RuleScanLog.id.desc()).limit(limit)).scalars().all()
    return [{
        "id": r.id, "scan_at": r.scan_at, "hit_count": r.hit_count,
        "exp_generated": r.exp_generated, "ctrl_skipped": r.ctrl_skipped,
        "freq_skipped": r.freq_skipped, "blacklist_skipped": r.blacklist_skipped,
        "dedup_skipped": r.dedup_skipped, "conflict_skipped": r.conflict_skipped,
        "status": r.status, "error": r.error, "duration_ms": r.duration_ms,
    } for r in rows]
