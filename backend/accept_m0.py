# -*- coding: utf-8 -*-
"""M0 本机全栈验收：拉起 uvicorn → 检查清单 → 输出结果并收尾。

    cd backend && ..\\.venv\\Scripts\\python.exe -X utf8 accept_m0.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
PY = sys.executable

server = subprocess.Popen(
    [PY, "-X", "utf8", "-m", "uvicorn", "app.main:app", "--port", "8000"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
results = {}
try:
    # 等待服务就绪（最多 15s）
    for _ in range(30):
        try:
            if httpx.get(BASE + "/api/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        raise RuntimeError("uvicorn 未能在 15s 内就绪")

    c = httpx.Client(base_url=BASE, timeout=10)
    results["health"] = c.get("/api/health").json()["status"] == "ok"
    results["swagger"] = c.get("/docs").status_code == 200

    def login(name, pw):
        r = c.post("/api/auth/login", json={"name": name, "password": pw})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    admin = login("admin", "admin123")
    ops = login("ops1", "ops123")
    cs = login("cs1", "cs123")
    results["3roles_login"] = True
    results["me"] = c.get("/api/auth/me", headers=cs).json()["role"] == "cs"
    results["admin_ping"] = c.get("/api/admin/ping", headers=admin).status_code == 200
    results["ops_ping"] = c.get("/api/ops/ping", headers=ops).status_code == 200
    results["cs_ping"] = c.get("/api/cs/ping", headers=cs).status_code == 200
    results["cs_admin_403"] = c.get("/api/admin/ping", headers=cs).status_code == 403
    results["cs_ops_403"] = c.get("/api/ops/ping", headers=cs).status_code == 403

    conn = sqlite3.connect("data/app.db")
    n403 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='access_denied'").fetchone()[0]
    results["audit_403_logged"] = n403 >= 2
    c.post("/api/auth/login", json={"name": "admin", "password": "bad"})
    nfail = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='login_failed'").fetchone()[0]
    results["audit_login_failed"] = nfail >= 1
    conn.close()
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()

ok = all(results.values())
report = {"results": results, "acceptance": "PASS" if ok else "FAIL"}
with open("acceptance_result.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1, ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
sys.exit(0 if ok else 1)
