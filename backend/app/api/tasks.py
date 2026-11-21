# -*- coding: utf-8 -*-
"""客服工作台 API（F4-03~F4-08/F4-11）+ 公共池认领（F4-12/R4）+ 黑名单管理（BR-02）。

BR-10：任务归属一律服务端注入（operator.id），篡改任务 ID 一律 403 记审计；
BR-05 状态单向流转，已完成不可回退；BR-07 全部变更留痕（task_state_log/touch_record）。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.db import get_db
from ..core.deps import require_cs_or_ops
from ..models.member import Blacklist, Member
from ..models.operator import Operator
from ..models.rule import Rule
from ..models.share import ShareDetail
from ..models.task import Task, TaskStateLog, TouchRecord
from ..rules.renderer import render

router = APIRouter(tags=["tasks"])

RESULT_ENUMS = {
    "renewed": "已续订", "considering": "考虑中", "not_now": "暂不续订",
    "unreachable": "联系不上", "refused": "会员拒绝", "other": "其他",
}


def _load_task_bundle(db: Session, task_id: int):
    task = db.get(Task, task_id)
    if task is None:
        return None, None, None, None
    member = db.get(Member, task.member_id)
    share = db.get(ShareDetail, task.share_detail_id)
    rule = db.get(Rule, task.rule_id)
    return task, member, share, rule


def _deny(operator: Operator, task_id: int, request: Optional[Request], db: Session):
    from ..core.db import SessionLocal

    with SessionLocal() as adb:
        write_audit(adb, actor_id=operator.id, action="access_denied",
                    object_type="task", object_id=str(task_id),
                    detail={"reason": "not-owner"},
                    ip=request.client.host if request and request.client else None)
    raise HTTPException(status_code=403, detail="无权操作该任务")


def _render_task(rule: Rule, member, share, cs: Optional[Operator]) -> str:
    if rule is None or member is None or share is None:
        return ""
    text, _missing = render(rule.template, member=member, share=share, cs=cs,
                            benefit_text=rule.benefit_text)
    return text

@router.get("/cs/tasks", summary="今日待办三分区（F4-03）")
def cs_tasks(zone: str = Query("today", pattern="^(overdue|today|upcoming)$"),
             page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             operator: Operator = Depends(require_cs_or_ops), db: Session = Depends(get_db)) -> dict:
    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today0 + timedelta(days=1)
    query = select(Task).where(Task.cs_id == operator.id, Task.status == "pending", Task.pool.is_(False))
    if zone == "overdue":
        query = query.where(Task.plan_time < today0)
    elif zone == "today":
        query = query.where(Task.plan_time >= today0, Task.plan_time < tomorrow)
    else:  # upcoming：计划在未来且 48h 内到期（F4-03 即将到期）
        query = query.where(Task.plan_time >= tomorrow,
                            Task.expire_deadline.is_not(None),
                            Task.expire_deadline <= now + timedelta(hours=48))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(Task.plan_time.asc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = []
    for t in rows:
        member = db.get(Member, t.member_id)
        share = db.get(ShareDetail, t.share_detail_id)
        rule = db.get(Rule, t.rule_id)
        cs = db.get(Operator, t.cs_id) if t.cs_id else None
        full_text = _render_task(rule, member, share, cs)
        items.append({
            "id": t.id, "member_id": t.member_id,
            "member_name": (member.real_name or member.nickname) if member else None,
            "share_type": share.share_type if share else None,
            "remain_times": share.remain_times if share else None,
            "plan_time": t.plan_time, "expire_deadline": t.expire_deadline,
            "content_preview": full_text[:60],
            "copied": t.copied_at is not None,
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/cs/tasks/{task_id}", summary="任务详情（F4-04）")
def cs_task_detail(task_id: int, operator: Operator = Depends(require_cs_or_ops),
                   db: Session = Depends(get_db)) -> dict:
    task, member, share, rule = _load_task_bundle(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.cs_id != operator.id and operator.role not in ("ops", "admin"):
        _deny(operator, task_id, None, db)
    cs = db.get(Operator, task.cs_id) if task.cs_id else None
    touches = db.scalars(select(TouchRecord).where(TouchRecord.member_id == task.member_id)
                         .order_by(TouchRecord.completed_at.desc()).limit(20)).all()
    return {
        "task": {"id": task.id, "status": task.status, "result": task.result,
                 "remark": task.remark, "plan_time": task.plan_time,
                 "copied_at": task.copied_at, "created_at": task.created_at},
        "member": {"id": member.id, "ext_member_id": member.ext_member_id,
                   "nickname": member.nickname, "real_name": member.real_name} if member else None,
        "share": {"share_type": share.share_type, "good_name": share.good_name,
                  "total_cnt": share.total_cnt, "shipped_cnt": share.shipped_cnt,
                  "remain_times": share.remain_times, "cycle_desc": share.cycle_desc,
                  "start_ship_date": share.start_ship_date,
                  "end_ship_date": share.end_ship_date} if share else None,
        "content": _render_task(rule, member, share, cs),
        "touch_history": [{"id": t.id, "result": t.result, "completed_at": t.completed_at}
                          for t in touches],
    }

class CompleteIn(BaseModel):
    result: str
    remark: Optional[str] = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class RescheduleIn(BaseModel):
    plan_time: datetime
    reason: str = Field(min_length=1, max_length=200)


def _owned_task(task_id: int, operator: Operator, request: Optional[Request],
                db: Session) -> Task:
    """任务归属校验（BR-10）：客服仅限本人任务；运营/超管按权限矩阵可操作全部任务。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.cs_id != operator.id and operator.role not in ("ops", "admin"):
        _deny(operator, task_id, request, db)
    return task


def _transition(db: Session, task: Task, to_status: str, operator_id: Optional[int],
                reason: Optional[str] = None) -> None:
    db.add(TaskStateLog(task_id=task.id, from_status=task.status, to_status=to_status,
                        operator_id=operator_id, reason=reason))


@router.post("/cs/tasks/{task_id}/copy", summary="复制文案留痕（F4-05，幂等）")
def copy_task(task_id: int, request: Request, operator: Operator = Depends(require_cs_or_ops),
              db: Session = Depends(get_db)) -> dict:
    task = _owned_task(task_id, operator, request, db)
    if task.copied_at is None:
        task.copied_at = datetime.now()
        db.commit()
    return {"copied_at": task.copied_at}


@router.post("/cs/tasks/{task_id}/complete", summary="标记完成 + 结果回填（F4-06）")
def complete_task(task_id: int, body: CompleteIn, request: Request,
                  operator: Operator = Depends(require_cs_or_ops), db: Session = Depends(get_db)) -> dict:
    if body.result not in RESULT_ENUMS:
        raise HTTPException(status_code=422, detail=f"result 必须是 {sorted(RESULT_ENUMS)}")
    if body.result == "other" and not (body.remark or "").strip():
        raise HTTPException(status_code=422, detail="选「其他」时备注必填（D11）")
    task = _owned_task(task_id, operator, request, db)
    if task.status != "pending":
        raise HTTPException(status_code=409, detail=f"任务状态为 {task.status}，不可完成（BR-05）")
    now = datetime.now()
    task.status = "done"
    task.result = body.result
    task.remark = body.remark
    task.completed_at = now
    _transition(db, task, "done", operator.id, reason=body.remark or body.result)
    member = db.get(Member, task.member_id)
    share = db.get(ShareDetail, task.share_detail_id)
    rule = db.get(Rule, task.rule_id)
    cs = operator
    db.add(TouchRecord(
        task_id=task.id, member_id=task.member_id, cs_id=operator.id,
        content_snapshot=_render_task(rule, member, share, cs),
        result=body.result, remark=body.remark,
        latency_seconds=int((now - task.created_at).total_seconds()) if task.created_at else None,
        completed_at=now,
    ))
    db.commit()
    return {"id": task.id, "status": "done", "completed_at": now}


@router.post("/cs/tasks/{task_id}/cancel", summary="取消任务（需原因）")
def cancel_task(task_id: int, body: ReasonIn, request: Request,
                operator: Operator = Depends(require_cs_or_ops), db: Session = Depends(get_db)) -> dict:
    task = _owned_task(task_id, operator, request, db)
    if task.status != "pending":
        raise HTTPException(status_code=409, detail=f"任务状态为 {task.status}，不可取消（BR-05）")
    task.status = "cancelled"
    _transition(db, task, "cancelled", operator.id, reason=body.reason)
    db.commit()
    return {"id": task.id, "status": "cancelled"}


@router.post("/cs/tasks/{task_id}/reschedule", summary="任务改期（需原因，P1）")
def reschedule_task(task_id: int, body: RescheduleIn, request: Request,
                    operator: Operator = Depends(require_cs_or_ops), db: Session = Depends(get_db)) -> dict:
    task = _owned_task(task_id, operator, request, db)
    if task.status != "pending":
        raise HTTPException(status_code=409, detail=f"任务状态为 {task.status}，不可改期（BR-05）")
    task.plan_time = body.plan_time
    _transition(db, task, "pending", operator.id, reason=f"reschedule:{body.reason}")
    db.commit()
    return {"id": task.id, "plan_time": task.plan_time}


@router.get("/cs/summary", summary="今日工作小结（F4-11）")
def cs_summary(operator: Operator = Depends(require_cs_or_ops), db: Session = Depends(get_db)) -> dict:
    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today0 + timedelta(days=1)
    base = select(Task).where(Task.cs_id == operator.id)

    should_contact = db.execute(select(func.count()).select_from(
        base.where(Task.status == "pending", Task.pool.is_(False),
                   Task.plan_time < tomorrow).subquery())).scalar() or 0
    overdue = db.execute(select(func.count()).select_from(
        base.where(Task.status == "pending", Task.pool.is_(False),
                   Task.plan_time < today0).subquery())).scalar() or 0
    done_today = db.scalars(base.where(
        Task.status == "done", Task.completed_at >= today0,
        Task.completed_at < tomorrow)).all()
    distribution: dict[str, int] = {}
    for t in done_today:
        distribution[t.result or "unknown"] = distribution.get(t.result or "unknown", 0) + 1
    return {"should_contact": should_contact, "contacted": len(done_today),
            "overdue": overdue, "result_distribution": distribution}
