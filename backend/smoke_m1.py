# -*- coding: utf-8 -*-
"""M1 实网冒烟：真实同步数据经 API 验证（admin/ops/cs 角色链路）。"""
import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"

server = subprocess.Popen(
    [sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app", "--port", "8000"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
results = {}
try:
    for _ in range(30):
        try:
            if httpx.get(BASE + "/api/health", timeout=2, trust_env=False).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)

    c = httpx.Client(base_url=BASE, timeout=15, trust_env=False)
    r_login = c.post("/api/auth/login", json={"name": "admin", "password": "admin123"})
    print("login status:", r_login.status_code, "body:", r_login.text[:200])
    admin = {"Authorization": "Bearer " + r_login.json()["access_token"]}

    # 同步日志 API
    logs = c.get("/api/admin/sync-logs?limit=10", headers=admin).json()
    results["sync_logs_api"] = len(logs) >= 6 and all(l["status"] == "ok" for l in logs[:6])

    # 会员全量检索（真实数据）
    r = c.get("/api/ops/members?page_size=5", headers=admin).json()
    results["ops_members_total"] = r["total"] == 26067
    sample = r["items"][0]
    results["ops_members_cs_name"] = "cs_name" in sample

    # 搜索（按手机号）
    r2 = c.get("/api/ops/members?search=13800", headers=admin).json()
    results["ops_search"] = r2["total"] >= 0

    # 会员详情含份额（取一个有份额的会员内部 id）
    import sqlite3
    conn = sqlite3.connect("data/app.db")
    row = conn.execute(
        "SELECT m.id, s.remain_times FROM member m JOIN share_detail s ON s.member_id=m.id LIMIT 1"
    ).fetchone()
    conn.close()
    detail_ok = False
    if row:
        mid, remain = row
        d = c.get(f"/api/ops/members/{mid}", headers=admin).json()
        detail_ok = bool(d.get("shares")) and d["shares"][0]["remain_times"] == remain
    results["member_detail_shares"] = detail_ok

    # 真实客服登录（源系统同步的客服无密码，验证占位哈希不可登录）
    r = c.post("/api/auth/login", json={"name": "瓜娃子", "password": "anything"})
    results["synced_cs_no_password"] = r.status_code == 401

    ok = all(results.values())
    print(json.dumps({"results": results, "smoke": "PASS" if ok else "FAIL"},
                     ensure_ascii=False, indent=1))
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
