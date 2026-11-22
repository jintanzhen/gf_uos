# -*- coding: utf-8 -*-
"""系统标签自动计算（F2-03）：剩≤4次 / 静默 / 高价值 Top20% / 新会员。

口径（v0.3.10 答复确认）：
- share_low   生效中份额（order_status 非 0删除/3完结）存在剩余次数 ≤ 4，tag_value 记最少剩次
- silent      距最近一次下单（pay_time 优先，退 modify_date；均为源系统本地业务时间）
              超过 30 天；从未下单的会员以注册时间为基线
- high_value  累计消费（ext_order.total_price 求和，排除空值）排名前 20%（有消费会员中）
- new_member  注册时间在 7 天内

幂等：重算时全量删除 tag_type='sys' 后重插（人工标签 manual 不受影响）；
expire 过滤由消费端（scanner/详情）处理。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models.member import Member, Tag
from ..models.order import ExtOrder
from ..models.share import ShareDetail

SILENT_DAYS = 30
NEW_MEMBER_DAYS = 7
LOW_REMAIN_MAX = 4
HIGH_VALUE_RATIO = 0.20


def compute_system_tags(db: Session, now: Optional[datetime] = None,
                        silent_days: int = SILENT_DAYS,
                        new_days: int = NEW_MEMBER_DAYS) -> dict:
    """全量重算四类系统标签，返回统计。人工标签（manual）不受影响。"""
    now = now or datetime.now()

    # 1) 清空旧系统标签（幂等）
    db.execute(delete(Tag).where(Tag.tag_type == "sys"))

    members = db.execute(select(Member.id, Member.ext_member_id, Member.register_time)).all()
    member_by_ext = {ext: mid for mid, ext, _reg in members}
    rows: list[Tag] = []

    # 2) 新会员：注册 ≤ N 天
    new_cutoff = now.timestamp() - new_days * 86400
    new_count = 0
    for _mid, _ext, reg in members:
        if reg is not None and reg.timestamp() >= new_cutoff:
            rows.append(Tag(member_id=_mid, tag_type="sys", tag_key="new_member",
                            tag_value=None))
            new_count += 1

    # 3) 剩≤4次：生效中份额存在 remain_times <= 4（取最少剩次记 value）
    low_rows = db.execute(
        select(ShareDetail.member_id, func.min(ShareDetail.remain_times))
        .where(ShareDetail.remain_times.is_not(None),
               ShareDetail.remain_times <= LOW_REMAIN_MAX,
               (ShareDetail.order_status.is_(None)) | (~ShareDetail.order_status.in_((0, 3))))
        .group_by(ShareDetail.member_id)
    ).all()
    low_count = 0
    for mid, min_remain in low_rows:
        rows.append(Tag(member_id=mid, tag_type="sys", tag_key="share_low",
                        tag_value=f"剩{min_remain}次"))
        low_count += 1

    # 4) 静默：最近下单时间（pay_time 优先，退 modify_date）超 N 天；无单以注册时间兜底
    last_order = dict(db.execute(
        select(ExtOrder.ext_mem_id, func.max(func.coalesce(ExtOrder.pay_time, ExtOrder.modify_date)))
        .where(ExtOrder.ext_mem_id.is_not(None))
        .group_by(ExtOrder.ext_mem_id)
    ).all())
    silent_count = 0
    for _mid, ext, reg in members:
        baseline = last_order.get(ext) or reg
        if baseline is None or baseline > now:
            continue
        idle_days = (now - baseline).days
        if idle_days >= silent_days:
            rows.append(Tag(member_id=_mid, tag_type="sys", tag_key="silent",
                            tag_value=f"{idle_days}天未下单"))
            silent_count += 1

    # 5) 高价值：有消费会员按累计 total_price 降序取前 20%（至少 1 人）
    spend_rows = db.execute(
        select(ExtOrder.ext_mem_id, func.sum(ExtOrder.total_price))
        .where(ExtOrder.ext_mem_id.is_not(None), ExtOrder.total_price.is_not(None))
        .group_by(ExtOrder.ext_mem_id)
        .order_by(func.sum(ExtOrder.total_price).desc())
    ).all()
    spend_rows = [(ext, float(total)) for ext, total in spend_rows if total and total > 0]
    high_count = 0
    if spend_rows:
        top_n = max(1, int(len(spend_rows) * HIGH_VALUE_RATIO))
        for ext, total in spend_rows[:top_n]:
            mid = member_by_ext.get(ext)
            if mid is None:
                continue
            rows.append(Tag(member_id=mid, tag_type="sys", tag_key="high_value",
                            tag_value=f"累计{round(total, 2)}元"))
            high_count += 1

    db.add_all(rows)
    db.commit()
    return {"members": len(members), "new_member": new_count, "share_low": low_count,
            "silent": silent_count, "high_value": high_count, "status": "ok"}


def active_tags_of(db: Session, member_id: int, now: Optional[datetime] = None) -> list[Tag]:
    """会员当前生效标签（未过期），系统在前、人工在后。"""
    now = now or datetime.now()
    rows = db.scalars(
        select(Tag).where(Tag.member_id == member_id).order_by(Tag.id.asc())
    ).all()
    return [t for t in rows if t.expire_at is None or t.expire_at > now]
