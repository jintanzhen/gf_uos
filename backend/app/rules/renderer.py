# -*- coding: utf-8 -*-
"""内容模板渲染（附录 C）：变量缺失渲染为空串并记警告，不阻断（PRD 5.4.1）。"""
from __future__ import annotations

from typing import Optional

SHARE_TYPE_LABELS = {"shucai": "蔬菜份额", "doufu": "豆制品份额", "douya": "豆芽份额"}

VARIABLES = ("会员昵称", "客服名", "客服二维码", "份额类型", "商品名",
             "剩余次数", "总次数", "配送周期", "续订权益")


def render(template: str, *, member, share, cs=None,
           benefit_text: Optional[str] = None) -> tuple[str, list[str]]:
    """渲染模板，返回 (文案, 缺失变量列表)。member/share/cs 为 ORM 对象。"""
    nickname = (getattr(member, "nickname", None) or getattr(member, "real_name", None) or "")
    values = {
        "会员昵称": nickname,
        "客服名": getattr(cs, "name", None) or "",
        "客服二维码": getattr(cs, "qrcode_url", None) or "",
        "份额类型": SHARE_TYPE_LABELS.get(share.share_type or "", share.share_type or ""),
        "商品名": share.good_name or "",
        "剩余次数": "" if share.remain_times is None else str(share.remain_times),
        "总次数": "" if share.total_cnt is None else str(share.total_cnt),
        "配送周期": share.cycle_desc or "",
        "续订权益": benefit_text or "",
    }
    missing = [k for k, v in values.items() if not v and ("{" + k + "}") in template]
    text = template
    for key, val in values.items():
        text = text.replace("{" + key + "}", val)
    return text, missing
