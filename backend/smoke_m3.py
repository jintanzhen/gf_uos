# -*- coding: utf-8 -*-
"""M3 实网冒烟：真实任务数据 -> 归因回补 -> 实验对比 -> 排行榜 -> 客服绩效 全链路。"""
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

    c = httpx.Client(base_url=BASE, timeout=30, trust_env=False)
    r = c.post("/api/auth/login", json={"name": "admin", "password": "admin123"})
    admin = {"Authorization": "Bearer " + r.json()["access_token"]}

    # 找到 M2 验收规则（有 266 条真实任务）
    rules = c.get("/api/ops/rules?search=M2", headers=admin).json()["items"]
    assert rules, "未找到 M2 验收规则"
    rule_id = rules[0]["id"]

    # F6-05 历史重算（幂等性验证：跑两遍）
    r1 = c.post("/api/ops/reports/recompute", json={"rule_id": rule_id}, headers=admin).json()
    r2 = c.post("/api/ops/reports/recompute", json={"rule_id": rule_id}, headers=admin).json()
    results["recompute"] = {"first": r1, "second": r2}
    results["recompute_idempotent"] = (r1["status"] == "ok" and r2["status"] == "ok"
                                       and r1["detected"] == r2["detected"])

    # F6-02 实验对比
    e = c.get(f"/api/ops/reports/experiment/{rule_id}", headers=admin).json()
    results["experiment"] = {
        "exp_generated": e["exp"]["generated"], "exp_done": e["exp"]["done"],
        "exp_renewals": e["exp"]["renewals"],
        "ctrl_members": e["ctrl"]["members"],
        "ctrl_renewals": e["ctrl"]["renewals"],
        "diff": e["diff"], "reliable": e["conclusion_reliable"],
    }
    results["experiment_ok"] = (e["exp"]["generated"] > 200
                                and e["ctrl"]["members"] > 50
                                and e["rule"]["attribution_days"] == 30)

    # F6-01 总览
    ov = c.get(f"/api/ops/reports/overview?rule_id={rule_id}", headers=admin).json()
    results["overview_ok"] = ov["generated"] > 200 and ov["completion_rate"] is not None

    # F6-06 排行榜 / F6-07 绩效
    rank = c.get("/api/ops/reports/rules-ranking", headers=admin).json()
    perf = c.get("/api/ops/reports/cs-performance", headers=admin).json()
    results["ranking_ok"] = len(rank) >= 1
    results["csperf_ok"] = len(perf) >= 1

    ok = all(v is True for k, v in results.items() if isinstance(v, bool))
    print(json.dumps({"results": results, "smoke": "PASS" if ok else "FAIL"},
                     ensure_ascii=False, indent=1))
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
