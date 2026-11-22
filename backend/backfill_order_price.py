# -*- coding: utf-8 -*-
"""一次性回填 ext_order.total_price / pay_time 存量（F2-03 高价值/静默标签口径）。

背景：total_price、pay_time 列随迁移 0004 加入 ORDER_MAP，历史订单同步时未写入
（实网 303,580 行仅 76 行有 total_price），高价值标签（累计消费 Top 20%）失真。

策略：分页全量拉源 OrderInfo（ID 升序），对 total_price IS NULL 的本地行按
ext_order_id 回填 total_price / pay_time。可重跑（幂等：只补空值）。
用法：..\.venv\Scripts\python.exe -X utf8 backend\backfill_order_price.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.order import ExtOrder  # noqa: E402
from app.spider.client import ZhlszClient  # noqa: E402
from app.spider.sync import _to_float as to_float, parse_dt  # noqa: E402


def main() -> None:
    client = ZhlszClient()
    db = SessionLocal()
    started = datetime.now()

    pending = dict(db.execute(
        select(ExtOrder.ext_order_id, ExtOrder.id)
        .where(ExtOrder.total_price.is_(None))
    ).all())
    print(f"待回填: {len(pending)} 行")

    filled_price = 0
    filled_pay = 0
    page = 1
    scanned = 0
    while True:
        rows = client.get_page("OrderInfo", page=page, rows=500,
                               sort="ID", order="asc").get("rows") or []
        if not rows:
            break
        for r in rows:
            ext_id = r.get("ID")
            if ext_id not in pending:
                continue
            scanned += 1
            price = to_float(r.get("TotalPrice"))
            pay_time = parse_dt(r.get("pay_time"))
            if price is None and pay_time is None:
                continue
            row = db.get(ExtOrder, pending[ext_id])
            if row is None:
                continue
            if price is not None and row.total_price is None:
                row.total_price = price
                filled_price += 1
            if pay_time and row.pay_time is None:
                row.pay_time = pay_time
                filled_pay += 1
        if page % 100 == 0:
            db.commit()
            print(f"  已扫描 {page * 500} 行，回填 {filled_price}")
        page += 1
        if page > 700:
            break
    db.commit()

    result = {
        "scanned_matched": scanned, "filled_total_price": filled_price,
        "filled_pay_time": filled_pay, "duration_s": (datetime.now() - started).seconds,
    }
    print("回填完成:", result)
    db.close()


if __name__ == "__main__":
    main()
