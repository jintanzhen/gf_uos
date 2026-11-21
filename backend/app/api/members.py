# -*- coding: utf-8 -*-
"""会员 360 API（M1）：
- GET /api/cs/members        客服「我的会员」（BR-10：归属一律取当前登录客服）
- GET /api/cs/members/{id}   会员详情（仅限自己名下会员，越权 404）
- GET /api/ops/members       运营/超管全量检索（分页+搜索）
- GET /api/ops/members/{id}  会员详情（含归属客服）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import require_cs, require_ops
from ..models.member import Member
from ..models.operator import CsMemberBinding, Operator
from ..models.share import ShareDetail

router = APIRouter(tags=["members"])


def _member_item(m: Member) -> dict:
    return {
        "id": m.id,
        "ext_member_id": m.ext_member_id,
        "nickname": m.nickname,
        "real_name": m.real_name,
        "mobile": m.mobile,
        "another_phone": m.another_phone,
        "register_time": m.register_time,
    }


def _share_item(s: ShareDetail) -> dict:
    return {
        "id": s.id,
        "ext_detail_id": s.ext_detail_id,
        "share_type": s.share_type,
        "good_name": s.good_name,
        "total_cnt": s.total_cnt,
        "shipped_cnt": s.shipped_cnt,
        "remain_times": s.remain_times,
        "cycle_desc": s.cycle_desc,
        "start_ship_date": s.start_ship_date,
        "end_ship_date": s.end_ship_date,
        "order_status": s.order_status,
        "sui_status": s.sui_status,
        "last_synced_at": s.last_synced_at,
    }


def _shares_of(db: Session, member_id: int) -> list[dict]:
    rows = db.execute(
        select(ShareDetail)
        .where(ShareDetail.member_id == member_id)
        .order_by(ShareDetail.remain_times.asc().nulls_last())
    ).scalars().all()
    return [_share_item(s) for s in rows]


def _search_filter(search: Optional[str]):
    if not search:
        return None
    like = f"%{search.strip()}%"
    conds = [
        Member.real_name.like(like),
        Member.nickname.like(like),
        Member.mobile.like(like),
    ]
    if search.strip().isdigit():
        conds.append(Member.ext_member_id == int(search))
    return or_(*conds)


def _share_stats(shares: list[dict]) -> tuple[int, Optional[int]]:
    """返回 (生效中份额数, 最少剩余次数)。order_status 0删除/3完结 视为失效。"""
    active = [s for s in shares if s["order_status"] not in (0, 3)]
    remains = [s["remain_times"] for s in active if s["remain_times"] is not None]
    return len(active), (min(remains) if remains else None)


# ---------------------------------------------------------------- 客服端

@router.get("/cs/members", summary="我的会员（BR-10 服务端注入归属）")
def cs_members(
    search: Optional[str] = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    operator=Depends(require_cs),
    db: Session = Depends(get_db),
) -> dict:
    base = (
        select(Member)
        .join(CsMemberBinding, CsMemberBinding.member_id == Member.id)
        .where(
            CsMemberBinding.cs_id == operator.id,
            CsMemberBinding.is_current.is_(True),
        )
    )
    flt = _search_filter(search)
    if flt is not None:
        base = base.where(flt)

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
    rows = db.execute(
        base.order_by(Member.ext_member_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    items = []
    for m in rows:
        item = _member_item(m)
        shares = _shares_of(db, m.id)
        item["share_count"], item["min_remain_times"] = _share_stats(shares)
        items.append(item)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/cs/members/{member_id}", summary="我的会员详情（越权 404）")
def cs_member_detail(
    member_id: int,
    operator=Depends(require_cs),
    db: Session = Depends(get_db),
) -> dict:
    bound = db.scalar(
        select(CsMemberBinding.id).where(
            CsMemberBinding.cs_id == operator.id,
            CsMemberBinding.member_id == member_id,
            CsMemberBinding.is_current.is_(True),
        )
    )
    member = db.get(Member, member_id) if bound else None
    if member is None:
        # 不存在与无权一律 404，避免枚举探测（BR-10）
        raise HTTPException(status_code=404, detail="会员不存在或不在您的名下")
    return {"member": _member_item(member), "shares": _shares_of(db, member_id)}


# ---------------------------------------------------------------- 运营端

@router.get("/ops/members", summary="会员全量检索（运营/超管）")
def ops_members(
    search: Optional[str] = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    operator=Depends(require_ops),
    db: Session = Depends(get_db),
) -> dict:
    query = select(Member)
    flt = _search_filter(search)
    if flt is not None:
        query = query.where(flt)

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(
        query.order_by(Member.ext_member_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    items = []
    for m in rows:
        item = _member_item(m)
        item["cs_name"] = db.execute(
            select(Operator.name)
            .join(CsMemberBinding, CsMemberBinding.cs_id == Operator.id)
            .where(CsMemberBinding.member_id == m.id, CsMemberBinding.is_current.is_(True))
        ).scalar()
        shares = _shares_of(db, m.id)
        item["share_count"], item["min_remain_times"] = _share_stats(shares)
        items.append(item)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/ops/members/{member_id}", summary="会员详情（运营/超管，含归属客服）")
def ops_member_detail(
    member_id: int,
    operator=Depends(require_ops),
    db: Session = Depends(get_db),
) -> dict:
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="会员不存在")
    cs_name = db.execute(
        select(Operator.name)
        .join(CsMemberBinding, CsMemberBinding.cs_id == Operator.id)
        .where(CsMemberBinding.member_id == member_id, CsMemberBinding.is_current.is_(True))
    ).scalar()
    return {
        "member": _member_item(member),
        "cs_name": cs_name,
        "shares": _shares_of(db, member_id),
    }


