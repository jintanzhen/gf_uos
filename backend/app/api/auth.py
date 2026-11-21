# -*- coding: utf-8 -*-
"""登录 API：POST /api/auth/login 签发 JWT；GET /api/auth/me 返回当前身份。

登录失败（含密码错误）写审计（action=login_failed），成功不写（减少噪音）。
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.deps import get_current_operator
from ..core.db import get_db
from ..core.security import create_access_token, verify_password
from ..models.operator import Operator
from ..schemas.auth import LoginRequest, OperatorOut, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="账号密码登录")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    operator = db.scalar(select(Operator).where(Operator.name == body.name))
    if operator is None or not verify_password(body.password, operator.password_hash):
        write_audit(
            db,
            actor_id=operator.id if operator else None,
            action="login_failed",
            object_type="operator",
            object_id=operator.id if operator else body.name,
            detail={"name": body.name},
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if operator.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

    token = create_access_token(operator.id, operator.role)
    return TokenResponse(access_token=token, operator=OperatorOut.model_validate(operator))


@router.get("/me", response_model=OperatorOut, summary="当前登录人")
def me(operator: Operator = Depends(get_current_operator)) -> OperatorOut:
    return OperatorOut.model_validate(operator)
