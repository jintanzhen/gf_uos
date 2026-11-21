# -*- coding: utf-8 -*-
"""角色权限依赖（BR-10）：服务端强制注入身份，前端传参一律不信任。

- require_cs    : 仅客服（cs 路由不存在可传 cs_id 的参数，归属一律取 current.id）
- require_ops   : 运营 + 超管（运营可见全部任务/会员，PRD 3.2 权限矩阵）
- require_admin : 仅超管
- 越权一律 403，并写入 audit_log（action=access_denied）
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..models.operator import Operator
from .audit import write_audit
from .db import SessionLocal, get_db
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIAL_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="登录态无效或已过期",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_operator(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Operator:
    import jwt as pyjwt

    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        raise _CREDENTIAL_ERROR
    operator = db.get(Operator, int(payload["sub"]))
    if operator is None or operator.status != "active":
        raise _CREDENTIAL_ERROR
    return operator


def _require_roles(*allowed_roles: str):
    def dependency(request: Request, operator: Operator = Depends(get_current_operator)) -> Operator:
        if operator.role not in allowed_roles:
            # 用独立会话写审计，保证即使请求会话回滚，越权记录也落库
            with SessionLocal() as audit_db:
                write_audit(
                    audit_db,
                    actor_id=operator.id,
                    action="access_denied",
                    object_type="endpoint",
                    object_id=str(request.url.path),
                    detail={"role": operator.role, "required": list(allowed_roles)},
                    ip=request.client.host if request.client else None,
                )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该资源")
        return operator

    return dependency


require_cs = _require_roles("cs")
require_cs_or_ops = _require_roles("cs", "ops", "admin")  # 工作台端点：客服本人 + 运营/超管（权限矩阵：运营可操作全部任务）
require_ops = _require_roles("ops", "admin")
require_admin = _require_roles("admin")
