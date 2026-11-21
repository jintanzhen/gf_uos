# -*- coding: utf-8 -*-
"""审计日志唯一写入口（BR-07/F5-03）：audit_log 只增不改不删。

- 全系统任何需要留痕的动作（登录失败、越权、导出、分组查看等）只允许通过本模块写入；
- 不提供任何 update/delete 方法；
- 应用层约定：禁止对 AuditLog 执行 UPDATE/DELETE（tests 骨架中固化）。
"""
import datetime as dt
import json
from typing import Any

from sqlalchemy.orm import Session

from .db import utcnow


def write_audit(
    db: Session,
    *,
    actor_id: int | None = None,
    action: str,
    object_type: str | None = None,
    object_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """写入一条审计记录并提交。失败不应影响主流程（审计尽力而为，但 403 场景需保证落库）。"""
    row = {
        "actor_id": actor_id,
        "action": action,
        "object_type": object_type,
        "object_id": str(object_id) if object_id is not None else None,
        "detail_json": json.dumps(detail, ensure_ascii=False) if detail else None,
        "ip": ip,
        "created_at": utcnow() or dt.datetime.utcnow(),
    }
    from app.models.system import AuditLog

    db.add(AuditLog(**row))
    db.commit()
