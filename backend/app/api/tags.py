# -*- coding: utf-8 -*-
"""标签体系 API（F2-03/F2-04）：
- POST /api/cs/members/{id}/tags   客服给自己名下会员打人工标签（越权 404）
- DELETE /api/cs/tags/{tag_id}     客服删除本人打的标签（审计留痕）
- POST /api/ops/members/{id}/tags  运营/超管给任意会员打标
- DELETE /api/ops/tags/{tag_id}    运营/超管删除人工标签
- GET  /api/ops/tags/keys          已用人工标签词表（规则编辑器下拉）
- POST /api/ops/tags/recompute     手动重算系统标签
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import write_audit
from ..core.db import get_db
from ..core.deps import require_cs, require_ops
from ..models.member import Member, Tag
from ..tags.service import active_tags_of, compute_system_tags

router = APIRouter(tags=["member-tags"])


class TagIn(BaseModel):
    tag_key: str = Field(min_length=1, max_length=20,
                         description="标签名，如：价格敏感/只收微信/勿扰/新客待跟进")
    expire_at: Optional[str] = Field(None, description="YYYY-MM-DD，空=永久有效")


def _parse_expire(expire_at: Optional[str]) -> Optional[datetime]:
    if not expire_at:
        return None
    try:
        d = datetime.strptime(expire_at, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="到期时间格式应为 YYYY-MM-DD")
    return d.replace(hour=23, minute=59, second=59)


def _add_manual_tag(db: Session, member_id: int, body: TagIn,
                    operator_id: int, request: Request, action: str) -> dict:
    key = body.tag_key.strip()
    if not key:
        raise HTTPException(status_code=422, detail="标签名不能为空")
    # 同会员同名未过期人工标签去重
    now = datetime.now()
    dup = db.scalar(select(Tag.id).where(
        Tag.member_id == member_id, Tag.tag_type == "manual", Tag.tag_key == key,
        Tag.expire_at.is_(None) | (Tag.expire_at > now)))
    if dup is not None:
        raise HTTPException(status_code=409, detail="该会员已存在同名未过期标签")
    tag = Tag(member_id=member_id, tag_type="manual", tag_key=key,
              expire_at=_parse_expire(body.expire_at), created_by=operator_id)
    db.add(tag)
    db.commit()
    write_audit(db, actor_id=operator_id, action=action, object_type="tag",
                object_id=str(tag.id), ip=request.client.host if request.client else None)
    return {"id": tag.id, "tag_key": key, "expire_at": body.expire_at}


def _delete_manual_tag(db: Session, tag_id: int, operator, request: Request,
                       creator_only_for_cs: bool) -> dict:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.tag_type != "manual":
        raise HTTPException(status_code=404, detail="标签不存在")
    if creator_only_for_cs and tag.created_by != operator.id:
        # 非本人所打一律 404，避免探测（与会员详情同策略）
        raise HTTPException(status_code=404, detail="标签不存在")
    key = tag.tag_key
    db.delete(tag)
    db.commit()
    write_audit(db, actor_id=operator.id, action="manual_tag_deleted",
                object_type="tag", object_id=str(tag_id),
                ip=request.client.host if request.client else None,
                detail={"tag_key": key})
    return {"deleted": tag_id}


# ---------------------------------------------------------------- 客服端

@router.post("/cs/members/{member_id}/tags", summary="客服打人工标签（仅本人名下，越权 404）")
def cs_add_tag(member_id: int, body: TagIn, request: Request,
               operator=Depends(require_cs), db: Session = Depends(get_db)) -> dict:
    from ..models.operator import CsMemberBinding
    bound = db.scalar(select(CsMemberBinding.id).where(
        CsMemberBinding.cs_id == operator.id,
        CsMemberBinding.member_id == member_id,
        CsMemberBinding.is_current.is_(True)))
    if not bound:
        raise HTTPException(status_code=404, detail="会员不存在或不在您的名下")
    return _add_manual_tag(db, member_id, body, operator.id, request,
                           action="manual_tag_added")


@router.delete("/cs/tags/{tag_id}", summary="客服删除本人打的标签（留痕）")
def cs_delete_tag(tag_id: int, request: Request,
                  operator=Depends(require_cs), db: Session = Depends(get_db)) -> dict:
    return _delete_manual_tag(db, tag_id, operator, request, creator_only_for_cs=True)


# ---------------------------------------------------------------- 运营端

@router.post("/ops/members/{member_id}/tags", summary="运营/超管打人工标签")
def ops_add_tag(member_id: int, body: TagIn, request: Request,
                operator=Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    if not db.get(Member, member_id):
        raise HTTPException(status_code=404, detail="会员不存在")
    return _add_manual_tag(db, member_id, body, operator.id, request,
                           action="manual_tag_added")


@router.delete("/ops/tags/{tag_id}", summary="运营/超管删除人工标签（留痕）")
def ops_delete_tag(tag_id: int, request: Request,
                   operator=Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    return _delete_manual_tag(db, tag_id, operator, request, creator_only_for_cs=False)


@router.get("/ops/tags/keys", summary="已用人工标签词表（规则编辑器下拉）")
def tag_keys(operator=Depends(require_ops), db: Session = Depends(get_db)) -> list[str]:
    rows = db.execute(
        select(Tag.tag_key).where(Tag.tag_type == "manual")
        .group_by(Tag.tag_key).order_by(func.count(Tag.id).desc())
    ).all()
    return [r[0] for r in rows]


@router.post("/ops/tags/recompute", summary="手动重算系统标签（幂等）")
def recompute_tags(operator=Depends(require_ops), db: Session = Depends(get_db)) -> dict:
    return compute_system_tags(db)
