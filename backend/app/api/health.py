# -*- coding: utf-8 -*-
"""系统与连通性端点：/health 无需鉴权；三个 ping 用于角色权限冒烟验证与前端连通检查。"""
from fastapi import APIRouter, Depends

from ..core.config import settings
from ..core.deps import require_admin, require_cs, require_ops
from ..models.operator import Operator

router = APIRouter(tags=["system"])


@router.get("/health", summary="健康检查（公开）")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@router.get("/cs/ping", summary="客服链路连通检查")
def cs_ping(operator: Operator = Depends(require_cs)) -> dict:
    return {"pong": True, "role": operator.role, "operator_id": operator.id}


@router.get("/ops/ping", summary="运营链路连通检查")
def ops_ping(operator: Operator = Depends(require_ops)) -> dict:
    return {"pong": True, "role": operator.role, "operator_id": operator.id}


@router.get("/admin/ping", summary="超管链路连通检查")
def admin_ping(operator: Operator = Depends(require_admin)) -> dict:
    return {"pong": True, "role": operator.role, "operator_id": operator.id}
