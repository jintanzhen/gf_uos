# -*- coding: utf-8 -*-
"""一次性回填：member.staff_name（负责员工）全量对齐源系统 + 重跑客服绑定。

背景：增量游标拿不到历史未变更行，member.staff_name 需先全量对齐一次，
之后 sync_member 增量（负责员工变更会 bump ModifyDate）自动维护。
可重跑（UPSERT 幂等：仅更新有变化的行，不动游标），回填后自动调用 sync_binding。
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime

import httpx

BASE = "http://127.0.0.1:8000"
PAGE_SIZE = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("greenos.backfill_staff")

server = subprocess.Popen(
    [sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app", "--port", "8000"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)


def main() -> None:
    from app.core.db import SessionLocal
    from app.models.member import Member
    from app.models.system import SyncLog
    from app.spider.client import ZhlszClient
    from app.spider.sync import run_sync

    try:
        for _ in range(30):
            try:
                if httpx.get(BASE + "/api/health", timeout=2, trust_env=False).status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)

        db = SessionLocal()
        client = ZhlszClient()

        started = datetime.utcnow()
        scanned = 0
        updated = 0
        staff_counter: dict[str, int] = {}
        page = 1
        while True:
            rows = (client.get_page("MemberInfo", page=page, rows=PAGE_SIZE,
                                    sort="ID", order="asc").get("rows") or [])
            if not rows:
                break
            for row in rows:
                ext_id = row.get("MemID")
                if ext_id is None:
                    continue
                scanned += 1
                staff = row.get("Staff") or None
                if staff:
                    staff_counter[staff] = staff_counter.get(staff, 0) + 1
                affected = db.query(Member).filter(Member.ext_member_id == ext_id).update(
                    {"staff_name": staff}, synchronize_session=False)
                if affected:
                    updated += 1
            if scanned % 5000 < PAGE_SIZE:
                db.commit()
            page += 1
        db.commit()

        before = db.execute(
            __import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM cs_member_binding WHERE is_current = 1")).scalar()
        total_before = before or 0

        result = run_sync("binding")
        binding_result = result.get("binding", result)  # run_sync 返回 {"binding": {...}} 包装
        db.close()

        detail = {
            "backfill": {"scanned": scanned, "updated": updated,
                         "staff_distribution": staff_counter},
            "bindings_before": total_before,
            "binding_result": binding_result,
        }
        db2 = SessionLocal()
        db2.add(SyncLog(sync_type="binding", status="ok",
                        total_source=scanned, total_local=binding_result.get("total_current", 0),
                        started_at=started, finished_at=datetime.utcnow(),
                        detail_json=json.dumps(detail, ensure_ascii=False)))
        db2.commit()
        db2.close()

        print(json.dumps(detail, ensure_ascii=False, indent=1))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
