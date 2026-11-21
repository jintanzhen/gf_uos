# -*- coding: utf-8 -*-
"""字段映射与解析工具（F1 可维护性：映射集中一处，源系统改版只改这里）。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


def parse_dt(value: Any) -> Optional[datetime]:
    """源系统时间字符串 '2026-03-10 16:09:27' → naive datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def clean_mobile(value: Any) -> Optional[str]:
    """手机号清洗：去空格/分隔符，仅保留数字。"""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


# ---------------------------------------------------------------- 映射表
# 源字段 → 本系统字段；未列出的源字段仅保留在 raw_json 中

STAFF_MAP = {
    "ID": "ext_cs_id",
    "StaffName": "name",
    "Phone": "phone",
    "QRCodeURL": "qrcode_url",
    "ModifyDate": "modify_date",
}

MEMBER_MAP = {
    "MemID": "ext_member_id",
    "NickName": "nickname",
    "RealName": "real_name",
    "Mobile": "mobile",
    "AnotherPhone": "another_phone",
    "Staff": "staff_name",
    "CreateDate": "register_time",
    "ModifyDate": "modify_date",
}

ORDER_MAP = {
    "ID": "ext_order_id",
    "MemID": "ext_mem_id",
    "OrderType": "order_type",
    "OrderStatus": "order_status",
    "SuiFenePeisongStatus": "sui_status",
    "ModifyDate": "modify_date",
    # M3 归因信号（F6-05）：新订单时间/金额/前后序关联
    "pay_time": "pay_time",
    "TotalPrice": "total_price",
    "MatchOrderID": "match_order_id",
    "OldOrderID": "old_order_id",
}

SHARE_MAP = {
    "ID": "ext_detail_id",
    "OrderID": "ext_order_id",
    "MemID": "ext_mem_id",
    "GoodID": "good_id",
    "LoopShipCount": "total_cnt",
    "LoopShipedTimes": "shipped_cnt",
    "RemainShipTimes": "remain_times",
    "LoopShipDescription": "cycle_desc",
    "StartShipDate": "start_ship_date",
    "EndShipDate": "end_ship_date",
    "ModifyDate": "modify_date",
}


def map_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {dst: row.get(src) for src, dst in mapping.items() if src in row}


def parse_member_list(raw: Optional[str]) -> list[str]:
    """StaffInfo.MemberList 逗号分隔 → 去重后的成员标识列表。"""
    if not raw:
        return []
    seen: dict[str, None] = {}
    for token in raw.replace("，", ",").split(","):
        token = token.strip()
        if token:
            seen.setdefault(token, None)
    return list(seen)
