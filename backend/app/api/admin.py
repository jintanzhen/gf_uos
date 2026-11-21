# -*- coding: utf-8 -*-
"""超管端：手动触发同步（F1-10）、同步日志/对账报告（F1-08）。

同步是长耗时操作：手动触发改为后台线程执行，立即返回 202，
进度通过 sync_log 轮询查看（M1 不做 WebSocket 推送）。
"""
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.deps import require_admin
from ..core.db import get_db
from ..core.security import hash_password
from ..models.operator import CsMemberBinding, Operator
from ..models.system import SyncLog
from ..models.task import Task
from ..spider import sync as sync_mod
from ..spider.sync import SYNC_TYPES

router = APIRouter(tags=["admin-sync"])

# 进程内后台同步线程句柄（单实例部署，ADR-1）
_sync_thread: threading.Thread | None = None


class SyncTriggerOut(BaseModel):
    started: bool
    detail: str


def _run_sync_background(sync_type: str) -> None:
    try:
        sync_mod.run_sync(sync_type)
    except Exception:  # run_sync 内部已逐类记 sync_log，此处兜底防线程静默死亡
        import logging

        logging.getLogger("greenos.sync").exception("background sync crashed")


@router.post("/admin/sync/{sync_type}/run", response_model=SyncTriggerOut,
             summary="手动触发同步（后台执行）")
def trigger_sync(
    sync_type: str,
    request: Request,
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> SyncTriggerOut:
    global _sync_thread
    if sync_type not in (*SYNC_TYPES, "all"):
        raise HTTPException(status_code=422, detail=f"未知 sync_type: {sync_type}")
    if _sync_thread is not None and _sync_thread.is_alive():
        raise HTTPException(status_code=409, detail="已有同步任务在后台执行")

    _sync_thread = threading.Thread(
        target=_run_sync_background, args=(sync_type,), name=f"sync-{sync_type}", daemon=True
    )
    _sync_thread.start()
    write_audit(
        db, actor_id=operator.id, action="sync_triggered",
        object_type="sync", object_id=sync_type,
        ip=request.client.host if request.client else None,
    )
    return SyncTriggerOut(
        started=True,
        detail=f"同步 {sync_type} 已在后台启动，请通过 GET /api/admin/sync-logs 查看进度",
    )


@router.get("/admin/sync-logs", summary="同步日志与对账报告")
def list_sync_logs(
    limit: int = 50,
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(SyncLog).order_by(SyncLog.started_at.desc()).limit(min(limit, 200))
    ).scalars().all()
    return [
        {
            "id": r.id,
            "sync_type": r.sync_type,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "status": r.status,
            "total_source": r.total_source,
            "total_local": r.total_local,
            "diff_count": r.diff_count,
            "detail": r.detail_json,
            "error": r.error,
        }
        for r in rows
    ]


# ---------------------------------------------------------------- 人员管理（方案 B）

_UNSET_PASSWORD = "!"  # 同步客服的不可登录占位（sync_staff 写入）


@router.get("/admin/operators", summary="人员列表（含账号状态/绑定会员数）")
def list_operators(
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    binding_counts: dict[int, int] = dict(
        db.query(CsMemberBinding.cs_id, func.count())
        .filter(CsMemberBinding.is_current.is_(True))
        .group_by(CsMemberBinding.cs_id)
        .all()
    )
    task_counts: dict[int, int] = dict(
        db.query(Task.cs_id, func.count())
        .filter(Task.status.in_(("pending", "done")))
        .group_by(Task.cs_id)
        .all()
    )
    rows = db.scalars(select(Operator).order_by(Operator.ext_cs_id.is_(None), Operator.id)).all()
    return [
        {
            "id": o.id,
            "name": o.name,
            "role": o.role,
            "status": o.status,
            "ext_cs_id": o.ext_cs_id,
            "phone": o.phone,
            "account_ready": o.password_hash != _UNSET_PASSWORD,
            "binding_count": binding_counts.get(o.id, 0),
            "task_count": task_counts.get(o.id, 0),
        }
        for o in rows
    ]


class ResetPasswordIn(BaseModel):
    password: str


class OperatorStatusIn(BaseModel):
    status: str


@router.post("/admin/operators/{operator_id}/reset-password", summary="重置登录密码")
def reset_password(
    operator_id: int,
    body: ResetPasswordIn,
    request: Request,
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if len(body.password) < 5:
        raise HTTPException(status_code=422, detail="密码至少 5 位")
    target = db.get(Operator, operator_id)
    if target is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    was_unset = target.password_hash == _UNSET_PASSWORD
    target.password_hash = hash_password(body.password)
    db.commit()
    write_audit(
        db, actor_id=operator.id,
        action="password_reset" if not was_unset else "account_activated",
        object_type="operator", object_id=str(operator_id),
        detail={"target": target.name, "initial": was_unset},
        ip=request.client.host if request.client else None,
    )
    return {"id": target.id, "name": target.name,
            "activated": was_unset, "status": "ok"}


@router.post("/admin/operators/{operator_id}/status", summary="停用/启用账号（停用触发 BR-06 任务转公共池）")
def set_operator_status(
    operator_id: int,
    body: OperatorStatusIn,
    request: Request,
    operator=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if body.status not in ("active", "left"):
        raise HTTPException(status_code=422, detail="status 仅支持 active / left")
    target = db.get(Operator, operator_id)
    if target is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    if target.id == operator.id:
        raise HTTPException(status_code=422, detail="不能停用自己的账号")
    if target.role == "admin":
        raise HTTPException(status_code=422, detail="超管账号不允许停用")
    target.status = body.status
    db.commit()
    write_audit(
        db, actor_id=operator.id,
        action="operator_status_changed",
        object_type="operator", object_id=str(operator_id),
        detail={"target": target.name, "status": body.status},
        ip=request.client.host if request.client else None,
    )
    return {"id": target.id, "name": target.name, "status": target.status,
            "note": "停用后其名下在途任务将于下一分钟 tick 自动转公共池（BR-06）"
                    if body.status == "left" else None}
