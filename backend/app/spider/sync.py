# -*- coding: utf-8 -*-
"""同步管线（F1）：staff → member → order → share → binding。

设计要点（对应 PRD/架构）：
- UPSERT 幂等（F1-07）：按 ext_* 唯一键 merge，重跑不产生重复
- 增量游标（spider_cursor）：按源表 ModifyDate 降序拉取，<= 游标即停；
  若服务端未按 ModifyDate 排序（顺序检测失败）自动回退全量
- 对账（F1-08 / BR-08）：每类同步写 sync_log，失败游标不前移、不阻断后续
- MemberList 双口径匹配（R1）：token 先按 MemID、再按 Mobile 匹配，统计各自命中
- 归属唯一：先全量置 is_current=0，再激活本轮列表（R1 触发器兜底）
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any, Iterator, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from .client import ZhlszClient
from .mappings import (
    MEMBER_MAP,
    ORDER_MAP,
    SHARE_MAP,
    STAFF_MAP,
    clean_mobile,
    map_row,
    parse_dt,
    parse_member_list,
    to_int,
)

logger = logging.getLogger("greenos.sync")

SYNC_TYPES = ("staff", "member", "order", "share", "binding")
FENE_TYPE = "FenE"

# 同步互斥锁：全局同一时刻只允许一个同步任务
_sync_lock = threading.Lock()


class SyncRunning(RuntimeError):
    """已有同步任务在执行。"""


def get_client() -> ZhlszClient:
    return ZhlszClient()


# ---------------------------------------------------------------- 游标

def get_cursor(db: Session, key: str) -> Optional[datetime]:
    from ..models.system import SpiderCursor

    row = db.get(SpiderCursor, key)
    return row.last_sync_time if row else None


def set_cursor(db: Session, key: str, value: datetime) -> None:
    from ..models.system import SpiderCursor

    row = db.get(SpiderCursor, key)
    if row is None:
        db.add(SpiderCursor(key=key, last_sync_time=value))
    else:
        row.last_sync_time = value


# ---------------------------------------------------------------- 对账

def _write_sync_log(
    db: Session,
    *,
    sync_type: str,
    started_at: datetime,
    finished_at: datetime,
    status: str = "ok",
    total_source: Optional[int] = None,
    total_local: Optional[int] = None,
    diff_count: Optional[int] = None,
    detail: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    from ..models.system import SyncLog

    db.add(
        SyncLog(
            sync_type=sync_type,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            total_source=total_source,
            total_local=total_local,
            diff_count=diff_count,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
            error=error,
        )
    )
    db.commit()


def _reconcile(total_source: int, total_local: int) -> int:
    return total_local - total_source


# ---------------------------------------------------------------- 拉取

def _iter_incremental(
    client: ZhlszClient,
    table: str,
    date_field: str,
    cursor: Optional[datetime],
    *,
    page_size: int = 10000,
    max_rows: Optional[int] = None,
) -> Iterator[dict[str, Any]]:
    """按 ModifyDate 降序拉取；<= 游标即停。顺序异常时回退全量。"""
    first = client.get_page(table, page=1, rows=min(page_size, 100), sort=date_field, order="desc")
    sample = (first.get("rows") or [])[:100]
    if len(sample) >= 2:
        d0 = parse_dt(sample[0].get(date_field))
        d1 = parse_dt(sample[-1].get(date_field))
        sorted_ok = d0 is not None and d1 is not None and d0 >= d1
    else:
        sorted_ok = True
    if cursor is not None and not sorted_ok:
        logger.warning("%s: 服务端未按 %s 降序返回，回退全量拉取", table, date_field)
        cursor = None

    def stop_when(row: dict[str, Any]) -> bool:
        if cursor is None:
            return False
        dt = parse_dt(row.get(date_field))
        return dt is not None and dt <= cursor

    yield from client.iter_page_rows(
        table, page_size=page_size, sort=date_field, order="desc", stop_when=stop_when,
        max_rows=max_rows,
    )


# ---------------------------------------------------------------- 各类同步

def sync_staff(db: Session, client: ZhlszClient) -> dict[str, Any]:
    """StaffInfo(10 行) → operator(role=cs)。本地账号不受影响。"""
    from ..models.operator import Operator

    started = datetime.utcnow()
    source_count = 0
    created = 0
    updated = 0
    max_modify: Optional[datetime] = None

    for row in _iter_incremental(client, "StaffInfo", "ModifyDate", get_cursor(db, "StaffInfo")):
        source_count += 1
        data = map_row(row, STAFF_MAP)
        ext_cs_id = to_int(data.get("ext_cs_id"))
        if ext_cs_id is None:
            continue
        modify = parse_dt(data.get("modify_date"))
        if modify and (max_modify is None or modify > max_modify):
            max_modify = modify

        op = db.query(Operator).filter(Operator.ext_cs_id == ext_cs_id).first()
        name = str(data.get("name") or f"客服{ext_cs_id}")
        if op is None:
            # 本地账号与源客服重名时加后缀保证唯一
            clash = db.query(Operator).filter(Operator.name == name, Operator.ext_cs_id.is_(None)).first()
            if clash:
                name = f"{name}({ext_cs_id})"
            op = Operator(
                ext_cs_id=ext_cs_id,
                name=name,
                role="cs",
                status="active",
                # 无初始密码：哈希占位，任何密码都无法通过 bcrypt 校验
                password_hash="!",
            )
            db.add(op)
            created += 1
        else:
            updated += 1
        op.name = name
        op.phone = clean_mobile(data.get("phone")) or op.phone
        op.qrcode_url = data.get("qrcode_url") or op.qrcode_url
        op.status = "active"
    db.commit()

    total_local = db.query(Operator).filter(Operator.ext_cs_id.is_not(None)).count()
    if max_modify:
        set_cursor(db, "StaffInfo", max_modify)
        db.commit()
    result = {
        "source": source_count, "created": created, "updated": updated,
        "local": total_local, "diff": _reconcile(source_count, total_local),
    }
    _write_sync_log(
        db, sync_type="staff", started_at=started, finished_at=datetime.utcnow(),
        total_source=source_count, total_local=total_local,
        diff_count=result["diff"], detail=result,
    )
    return result


def sync_member(db: Session, client: ZhlszClient) -> dict[str, Any]:
    """memberinfo → member（全量 2.6 万行 ≈ 14s，每日全量 + ModifyDate 增量兜底）。"""
    from ..models.member import Member

    started = datetime.utcnow()
    cursor = get_cursor(db, "memberinfo")
    source_count = 0
    created = 0
    updated = 0
    skipped = 0
    max_modify: Optional[datetime] = None
    seen: set[int] = set()  # 源系统排序不稳定，同一行可能跨页重复

    for row in _iter_incremental(client, "memberinfo", "ModifyDate", cursor):
        ext_id_pre = to_int(row.get("MemID"))
        if ext_id_pre is not None:
            if ext_id_pre in seen:
                continue
            seen.add(ext_id_pre)
        source_count += 1
        data = map_row(row, MEMBER_MAP)
        ext_member_id = to_int(data.get("ext_member_id"))
        if ext_member_id is None:
            skipped += 1
            continue
        modify = parse_dt(data.get("modify_date"))
        if modify and (max_modify is None or modify > max_modify):
            max_modify = modify

        member = db.query(Member).filter(Member.ext_member_id == ext_member_id).first()
        if member is None:
            member = Member(ext_member_id=ext_member_id)
            db.add(member)
            created += 1
        else:
            updated += 1
        member.nickname = data.get("nickname")
        member.real_name = data.get("real_name")
        member.mobile = clean_mobile(data.get("mobile"))
        member.another_phone = clean_mobile(data.get("another_phone"))
        member.staff_name = data.get("staff_name") or None  # 负责员工（客服归属主口径）
        member.register_time = parse_dt(data.get("register_time"))
        member.raw_json = json.dumps(row, ensure_ascii=False)
        if source_count % 2000 == 0:
            db.commit()
    db.commit()

    total_local = db.query(Member).count()
    if max_modify:
        set_cursor(db, "memberinfo", max_modify)
        db.commit()
    result = {
        "source": source_count, "created": created, "updated": updated,
        "skipped": skipped, "local": total_local,
        "diff": _reconcile(source_count, total_local) if cursor is None else None,
    }
    _write_sync_log(
        db, sync_type="member", started_at=started, finished_at=datetime.utcnow(),
        total_source=source_count, total_local=total_local,
        diff_count=result["diff"], detail=result,
    )
    return result


def sync_order(db: Session, client: ZhlszClient) -> dict[str, Any]:
    """OrderInfo → ext_order（最小字段暂存，为 FenE 判定与状态回填服务）。"""
    from ..models.order import ExtOrder

    started = datetime.utcnow()
    cursor = get_cursor(db, "OrderInfo")

    # 预载 ext_order_id → (modify, type, status, sui, pay_time)，避免 30 万次单查
    existing: dict[str, tuple[Optional[datetime], Optional[str], Optional[int], Optional[str], Optional[datetime]]] = {}
    for oid, modify, otype, ostatus, sui, paytime in db.query(
        ExtOrder.ext_order_id, ExtOrder.modify_date, ExtOrder.order_type,
        ExtOrder.order_status, ExtOrder.sui_status, ExtOrder.pay_time,
    ):
        existing[oid] = (modify, otype, ostatus, sui, paytime)

    source_count = 0
    created = 0
    updated = 0
    max_modify: Optional[datetime] = None
    seen: set[str] = set()  # 源系统排序不稳定，同一行可能跨页重复
    now = datetime.utcnow()

    for row in _iter_incremental(client, "OrderInfo", "ModifyDate", cursor):
        oid_pre = row.get("ID")
        if oid_pre:
            if oid_pre in seen:
                continue
            seen.add(oid_pre)
        source_count += 1
        data = map_row(row, ORDER_MAP)
        ext_order_id = data.get("ext_order_id")
        if not ext_order_id:
            continue
        modify = parse_dt(data.get("modify_date"))
        if modify and (max_modify is None or modify > max_modify):
            max_modify = modify

        vals = (
            modify,
            data.get("order_type"),
            to_int(data.get("order_status")),
            data.get("sui_status"),
            parse_dt(data.get("pay_time")),
        )
        price = _to_float(data.get("total_price"))
        match_id = data.get("match_order_id") or None
        old_id = data.get("old_order_id") or None
        hit = existing.get(ext_order_id)
        if hit is None:
            db.add(
                ExtOrder(
                    ext_order_id=ext_order_id,
                    ext_mem_id=to_int(data.get("ext_mem_id")),
                    order_type=vals[1], order_status=vals[2], sui_status=vals[3],
                    modify_date=vals[0], pay_time=vals[4],
                    total_price=price, match_order_id=match_id, old_order_id=old_id,
                    last_synced_at=now,
                )
            )
            created += 1
        elif (hit[0], hit[1], hit[2], hit[3], hit[4]) != vals:
            db.query(ExtOrder).filter(ExtOrder.ext_order_id == ext_order_id).update(
                {
                    "ext_mem_id": to_int(data.get("ext_mem_id")),
                    "order_type": vals[1], "order_status": vals[2], "sui_status": vals[3],
                    "modify_date": vals[0], "pay_time": vals[4],
                    "total_price": price, "match_order_id": match_id, "old_order_id": old_id,
                    "last_synced_at": now,
                },
                synchronize_session=False,
            )
            updated += 1
        if source_count % 5000 == 0:
            db.commit()
    db.commit()

    total_local = db.query(ExtOrder).count()
    if max_modify:
        set_cursor(db, "OrderInfo", max_modify)
        db.commit()
    result = {"source": source_count, "created": created, "updated": updated, "local": total_local}
    _write_sync_log(
        db, sync_type="order", started_at=started, finished_at=datetime.utcnow(),
        total_source=source_count, total_local=total_local, detail=result,
    )
    return result


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_by_name(name: str) -> Optional[str]:
    """名称关键词分类（实测 v0.3.4：CaipinInfo.GoodJstSkuCode 全空，正式链路不可用）。

    豆腐/豆制品→doufu；豆芽→douya；其余份额商品（蔬菜/水果/蘑菇等）→shucai。
    """
    n = name or ""
    if "豆腐" in n or "豆制品" in n or "豆干" in n:
        return "doufu"
    if "豆芽" in n:
        return "douya"
    return "shucai"


def _build_good_type_maps(db: Session, client: ZhlszClient) -> tuple[dict[int, Optional[str]], dict[int, Optional[str]]]:
    """GoodID → (share_type, good_name)。

    链路1（正式，保留）：jstGood.sku_id ↔ CaipinInfo.GoodJstSkuCode → FeneType
    链路2（实测兜底 v0.3.4）：jstGood.GoodsType='FenE' 识别份额商品，名称关键词分类
    """
    sku_to_type: dict[str, str] = {}
    good_to_sku: dict[int, str] = {}
    good_to_name: dict[int, str] = {}
    fene_goods: set[int] = set()

    try:
        caipin_rows = list(client.iter_page_rows("CaipinInfo", page_size=1000, max_rows=5000))
        for row in caipin_rows:
            sku = row.get("GoodJstSkuCode")
            ftype = row.get("FeneType")
            if sku and ftype:
                sku_to_type[str(sku).strip()] = str(ftype).strip()
        good_rows = list(client.iter_page_rows("jstGood", page_size=5000, sort="ModifyDate"))
        for row in good_rows:
            gid = to_int(row.get("ID"))
            if gid is None:
                continue
            sku = row.get("sku_id") or row.get("SkuId") or row.get("SkuID")
            name = (row.get("GoodName") or row.get("short_name")
                    or row.get("name") or row.get("GoodsName"))
            if sku:
                good_to_sku[gid] = str(sku).strip()
            if name:
                good_to_name[gid] = str(name)
            if row.get("GoodsType") == "FenE":
                fene_goods.add(gid)
    except Exception as exc:  # best-effort：映射失败不阻断份额同步
        logger.warning("jstGood/CaipinInfo 拉取失败，share_type 将为空: %s", exc)
        return {}, {}

    type_map: dict[int, Optional[str]] = {}
    for gid, sku in good_to_sku.items():
        t = sku_to_type.get(sku)
        if t:
            type_map[gid] = t
        elif gid in fene_goods:
            type_map[gid] = _classify_by_name(good_to_name.get(gid, ""))
    return type_map, good_to_name


def sync_share(db: Session, client: ZhlszClient) -> dict[str, Any]:
    """OrderDetail → share_detail：仅保留 FenE 订单明细（决议 D1/D2）。"""
    from ..models.member import Member
    from ..models.order import ExtOrder
    from ..models.share import ShareDetail

    started = datetime.utcnow()
    cursor = get_cursor(db, "OrderDetail")

    # 预载：订单映射 + 会员映射（MemID → member.id）
    order_map: dict[str, tuple[Optional[str], Optional[int], Optional[str]]] = {}
    for oid, otype, ostatus, sui in db.query(
        ExtOrder.ext_order_id, ExtOrder.order_type, ExtOrder.order_status, ExtOrder.sui_status
    ):
        order_map[oid] = (otype, ostatus, sui)
    member_map: dict[int, int] = dict(db.query(Member.ext_member_id, Member.id).all())

    type_map, name_map = _build_good_type_maps(db, client)

    source_count = 0
    created = 0
    updated = 0
    skipped_not_fene = 0
    skipped_no_order = 0
    skipped_no_member = 0
    max_modify: Optional[datetime] = None
    seen: set[str] = set()  # 源系统排序不稳定，同一行可能跨页重复
    now = datetime.utcnow()

    for row in _iter_incremental(client, "OrderDetail", "ModifyDate", cursor, page_size=5000):
        source_count += 1
        modify = parse_dt(row.get("ModifyDate"))
        if modify and (max_modify is None or modify > max_modify):
            max_modify = modify
        did = row.get("ID")
        if not did or did in seen:
            continue
        seen.add(did)
        source_count += 1
        data = map_row(row, SHARE_MAP)
        ext_detail_id = data.get("ext_detail_id")
        if not ext_detail_id:
            continue

        order = order_map.get(data.get("ext_order_id") or "")
        if order is None:
            skipped_no_order += 1
            continue
        if order[0] != FENE_TYPE:
            skipped_not_fene += 1
            continue
        ext_mem_id = to_int(data.get("ext_mem_id"))
        member_id = member_map.get(ext_mem_id) if ext_mem_id is not None else None
        if member_id is None:
            skipped_no_member += 1
            continue

        good_id = to_int(data.get("good_id"))
        start = parse_dt(data.get("start_ship_date"))
        end = parse_dt(data.get("end_ship_date"))
        vals = {
            "member_id": member_id,
            "share_type": type_map.get(good_id) if good_id else None,
            "good_name": name_map.get(good_id) if good_id else None,
            "total_cnt": to_int(data.get("total_cnt")),
            "shipped_cnt": to_int(data.get("shipped_cnt")),
            "remain_times": to_int(data.get("remain_times")),
            "cycle_desc": data.get("cycle_desc"),
            "start_ship_date": start.date() if start else None,
            "end_ship_date": end.date() if end else None,
            "order_status": order[1],
            "sui_status": order[2],
            "last_synced_at": now,
        }
        existing = db.query(ShareDetail).filter(ShareDetail.ext_detail_id == ext_detail_id).first()
        if existing is None:
            db.add(ShareDetail(ext_detail_id=ext_detail_id, ext_order_id=data.get("ext_order_id"), **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(existing, k, v)
            updated += 1
        if source_count % 5000 == 0:
            db.commit()
            logger.info("share progress: %d rows processed, inserted=%d updated=%d skipped(fene=%d noorder=%d nomem=%d)",
                        source_count, created, updated, skipped_not_fene, skipped_no_order, skipped_no_member)
    db.commit()

    total_local = db.query(ShareDetail).count()
    if max_modify:
        set_cursor(db, "OrderDetail", max_modify)
        db.commit()
    result = {
        "source": source_count, "created": created, "updated": updated,
        "skipped_not_fene": skipped_not_fene, "skipped_no_order": skipped_no_order,
        "skipped_no_member": skipped_no_member, "local": total_local,
    }
    _write_sync_log(
        db, sync_type="share", started_at=started, finished_at=datetime.utcnow(),
        total_source=source_count, total_local=total_local, detail=result,
    )
    return result


def sync_binding(db: Session, client: ZhlszClient) -> dict[str, Any]:
    """cs_member_binding 重建（R1 唯一归属）：三口径按优先级匹配。

    口径 a（主）：MemberInfo.Staff 负责员工姓名 → Operator.name（source="MemberInfo.Staff"）
    口径 b（辅1）：StaffInfo.MemberList MemID 串（source="StaffInfo"）
    口径 c（辅2）：手机号（source="Mobile"）
    一个会员被多口径命中时取优先级最高者；已生成任务不重排（BR-01）。
    """
    from ..models.member import Member
    from ..models.operator import CsMemberBinding, Operator

    started = datetime.utcnow()

    # 全量置零（R1：先清后建，触发器不会拦截）
    db.execute(update(CsMemberBinding).values(is_current=False))
    db.commit()

    operators = db.query(Operator).filter(
        Operator.ext_cs_id.is_not(None), Operator.status == "active"
    ).order_by(Operator.ext_cs_id).all()

    # 口径 a 用的姓名 → 客服映射（同名多客服取 ext_cs_id 最小者）
    op_by_name: dict[str, Operator] = {}
    for op in operators:
        op_by_name.setdefault(op.name, op)

    # 预载会员三种匹配键 → member 内部 id
    members_by_id: dict[int, int] = {}
    members_by_mobile: dict[str, int] = {}
    assignments: dict[int, tuple[int, str, int]] = {}
    matched_by_staff = 0
    staff_unmatched_names: set[str] = set()
    for ext_id, mobile, staff_name, mid in db.query(
        Member.ext_member_id, Member.mobile, Member.staff_name, Member.id
    ):
        members_by_id[ext_id] = mid
        if mobile:
            members_by_mobile.setdefault(mobile, mid)
        # 口径 a：逐会员按负责员工姓名查客服（source="MemberInfo.Staff"）
        if staff_name:
            op = op_by_name.get(staff_name)
            if op is None:
                staff_unmatched_names.add(staff_name)
            else:
                assignments[mid] = (op.id, "MemberInfo.Staff", 0)
                matched_by_staff += 1

    # 口径 b/c：StaffInfo.MemberList 一次性全量拉取（行数少）
    matched_by_memid = 0
    matched_by_mobile = 0
    unmatched: list[dict[str, Any]] = []
    staff_rows = client.get_page("StaffInfo", page=1, rows=100, sort="ID", order="asc").get("rows") or []
    for staff in staff_rows:
        op = next((o for o in operators if o.ext_cs_id == to_int(staff.get("ID"))), None)
        if op is None:
            continue
        for token in parse_member_list(staff.get("MemberList")):
            member_id: Optional[int] = None
            by = None
            if token.isdigit():
                ext_id = to_int(token)
                if ext_id is not None and ext_id in members_by_id:
                    member_id = members_by_id[ext_id]
                    by = "memid"
            if member_id is None:
                digits = clean_mobile(token)
                if digits and digits in members_by_mobile:
                    member_id = members_by_mobile[digits]
                    by = "mobile"
            if member_id is None:
                unmatched.append({"staff": op.name, "token": token})
                continue
            priority = 1 if by == "memid" else 2
            if by == "memid":
                matched_by_memid += 1
            else:
                matched_by_mobile += 1
            prev = assignments.get(member_id)
            if prev is None or priority < prev[2]:
                assignments[member_id] = (op.id, "StaffInfo" if by == "memid" else "Mobile", priority)

    # 落库：upsert 幂等，source 记录取用口径
    bindings_created = 0
    bindings_reactivated = 0
    bindings_updated = 0
    for member_id, (cs_id, source, _prio) in assignments.items():
        binding = (
            db.query(CsMemberBinding)
            .filter(CsMemberBinding.cs_id == cs_id, CsMemberBinding.member_id == member_id)
            .first()
        )
        if binding is None:
            db.add(CsMemberBinding(cs_id=cs_id, member_id=member_id,
                                   is_current=True, source=source))
            bindings_created += 1
        elif not binding.is_current or binding.source != source:
            binding.is_current = True
            binding.source = source
            bindings_updated += 1
        else:
            binding.is_current = True
            bindings_reactivated += 1
    db.commit()

    total_current = db.query(CsMemberBinding).filter(CsMemberBinding.is_current.is_(True)).count()
    result = {
        "operators": len(operators),
        "matched_by_staff": matched_by_staff,
        "matched_by_memid": matched_by_memid,
        "matched_by_mobile": matched_by_mobile,
        "staff_unmatched_names": sorted(staff_unmatched_names),
        "bindings_created": bindings_created,
        "bindings_updated": bindings_updated,
        "bindings_reactivated": bindings_reactivated,
        "total_current": total_current,
        "unmatched_count": len(unmatched),
        "unmatched_sample": unmatched[:20],
    }
    _write_sync_log(
        db, sync_type="binding", started_at=started, finished_at=datetime.utcnow(),
        total_source=matched_by_staff + matched_by_memid + matched_by_mobile + len(unmatched),
        total_local=total_current, detail=result,
    )
    return result


# ---------------------------------------------------------------- 编排入口

def run_sync(sync_type: str = "all", *, client: Optional[ZhlszClient] = None) -> dict[str, Any]:
    """同步入口。sync_type: staff/member/order/share/binding/all。

    - 失败不阻断（BR-08）：单类失败记 sync_log(failed) 后继续后续类型
    - 互斥：全局锁，重复触发抛 SyncRunning
    """
    if sync_type not in (*SYNC_TYPES, "all"):
        raise ValueError(f"未知 sync_type: {sync_type}")
    if not _sync_lock.acquire(blocking=False):
        raise SyncRunning("已有同步任务在执行，请稍后")

    started_all = datetime.utcnow()
    results: dict[str, Any] = {}
    try:
        cli = client or get_client()
        # 单线程内复用 SessionLocal，每类同步独立事务
        from ..core.db import SessionLocal

        steps = (
            ["staff", "member", "order", "share", "binding"]
            if sync_type == "all"
            else [sync_type]
        )
        for step in steps:
            step_started = datetime.utcnow()
            with SessionLocal() as db:
                try:
                    if step == "staff":
                        results["staff"] = sync_staff(db, cli)
                    elif step == "member":
                        results["member"] = sync_member(db, cli)
                    elif step == "order":
                        results["order"] = sync_order(db, cli)
                    elif step == "share":
                        results["share"] = sync_share(db, cli)
                    elif step == "binding":
                        results["binding"] = sync_binding(db, cli)
                except Exception as exc:  # BR-08：失败不阻断
                    logger.exception("sync %s failed", step)
                    db.rollback()
                    _write_sync_log(
                        db, sync_type=step, started_at=step_started,
                        finished_at=datetime.utcnow(), status="failed", error=str(exc),
                    )
                    results[step] = {"status": "failed", "error": str(exc)}
        results["_elapsed_seconds"] = round((datetime.utcnow() - started_all).total_seconds(), 1)
        return results
    finally:
        _sync_lock.release()
