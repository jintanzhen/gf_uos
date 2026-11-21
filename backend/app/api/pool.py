# -*- coding: utf-8 -*-
"""运营端：公共池认领（F4-12/R4）与黑名单管理（BR-02）。"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.db import get_db
from ..core.deps import require_ops
from ..models.member import Blacklist, Member
from ..models.operator import Operator
from ..models.task import Task, TaskStateLog

router = APIRouter(tags=["pool"])


@router.get("/ops/pool", summary="公共池待办列表")
def pool_tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               operator: Operator = Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    query = select(Task).where(Task.pool.is_(True), Task.status == "pending")
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(Task.plan_time.asc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "items": [{
        "id": t.id, "member_id": t.member_id, "rule_id": t.rule_id,
        "plan_time": t.plan_time, "expire_deadline": t.expire_deadline,
    } for t in rows]}


@router.post("/ops/pool/{task_id}/claim", summary="认领公共池任务（归属认领人并留痕）")
def claim_task(task_id: int, request: Request, operator: Operator = Depends(require_ops),
               db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or not task.pool or task.status != "pending":
        raise HTTPException(status_code=404, detail="任务不存在或不可认领")
    task.cs_id = operator.id
    task.pool = False
    db.add(TaskStateLog(task_id=task.id, from_status="pending", to_status="pending",
                        operator_id=operator.id, reason="pool-claim"))
    db.commit()
    write_audit(db, actor_id=operator.id, action="pool_claimed",
                object_type="task", object_id=str(task.id),
                ip=request.client.host if request.client else None)
    return {"id": task.id, "cs_id": operator.id}


class BlacklistIn(BaseModel):
    member_id: int
    until_date: Optional[str] = Field(default=None, description="YYYY-MM-DD，空=永久")
    reason: Optional[str] = Field(default=None, max_length=200)


@router.get("/ops/blacklist", summary="黑名单列表")
def list_blacklist(operator: Operator = Depends(require_ops),
                   db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(Blacklist).order_by(Blacklist.id.desc())).scalars().all()
    return [{
        "id": b.id, "member_id": b.member_id, "is_active": b.is_active,
        "until_date": b.until_date, "reason": b.reason,
    } for b in rows]


@router.post("/ops/blacklist", summary="加入黑名单（BR-02：在途任务自动取消）")
def add_blacklist(body: BlacklistIn, request: Request, operator: Operator = Depends(require_ops),
                  db: Session = Depends(get_db)) -> dict:
    if db.get(Member, body.member_id) is None:
        raise HTTPException(status_code=404, detail="会员不存在")
    until = datetime.strptime(body.until_date, "%Y-%m-%d").date() if body.until_date else None
    bl = db.scalar(select(Blacklist).where(Blacklist.member_id == body.member_id))
    if bl is None:
        bl = Blacklist(member_id=body.member_id, is_active=True)
        db.add(bl)
    bl.is_active = True
    bl.until_date = until
    bl.reason = body.reason
    bl.created_by = operator.id
    # BR-02：取消该会员全部在途任务
    pending = db.scalars(select(Task).where(Task.member_id == body.member_id,
                                            Task.status == "pending")).all()
    for t in pending:
        t.status = "cancelled"
        db.add(TaskStateLog(task_id=t.id, from_status="pending", to_status="cancelled",
                            operator_id=operator.id, reason="blacklisted"))
    db.commit()
    write_audit(db, actor_id=operator.id, action="blacklist_added",
                object_type="member", object_id=str(body.member_id),
                detail={"cancelled_tasks": len(pending)},
                ip=request.client.host if request.client else None)
    return {"member_id": body.member_id, "is_active": True, "cancelled_tasks": len(pending)}


@router.post("/ops/blacklist/{blacklist_id}/unblock", summary="解除黑名单（保留历史）")
def unblock(blacklist_id: int, request: Request, operator: Operator = Depends(require_ops),
            db: Session = Depends(get_db)) -> dict:
    bl = db.get(Blacklist, blacklist_id)
    if bl is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    bl.is_active = False
    db.commit()
    write_audit(db, actor_id=operator.id, action="blacklist_removed",
                object_type="member", object_id=str(bl.member_id),
                ip=request.client.host if request.client else None)
    return {"id": bl.id, "is_active": False}
