# -*- coding: utf-8 -*-
"""M2 实网冒烟：真实份额数据 -> 规则 -> 预览 -> 扫描 -> 公共池认领 -> 完成回填 全闭环。"""
import json
import sqlite3
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

    c = httpx.Client(base_url=BASE, timeout=20, trust_env=False)

    def login(name, pw):
        r = c.post("/api/auth/login", json={"name": name, "password": pw})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    admin = login("admin", "admin123")
    ops = login("ops1", "ops123")

    # 清理历史验收数据，保证脚本可重复执行（先收集 rule_id 再删，避免孤儿任务）
    old_ids = [o["id"] for o in c.get("/api/ops/rules?search=M2", headers=admin).json()["items"]]
    conn = sqlite3.connect("data/app.db")
    if old_ids:
        marks = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM task_state_log WHERE task_id IN (SELECT id FROM task WHERE rule_id IN ({marks}))", old_ids)
        conn.execute(f"DELETE FROM touch_record WHERE task_id IN (SELECT id FROM task WHERE rule_id IN ({marks}))", old_ids)
        conn.execute(f"DELETE FROM task WHERE rule_id IN ({marks})", old_ids)
        conn.execute(f"DELETE FROM rule_experiment_member WHERE rule_id IN ({marks})", old_ids)
        conn.commit()
    for old in old_ids:
        c.delete(f"/api/ops/rules/{old}", headers=admin)
    conn.execute("DELETE FROM task_state_log WHERE task_id IN (SELECT id FROM task WHERE rule_id NOT IN (SELECT id FROM rule))")
    conn.execute("DELETE FROM touch_record WHERE task_id IN (SELECT id FROM task WHERE rule_id NOT IN (SELECT id FROM rule))")
    conn.execute("DELETE FROM task WHERE rule_id NOT IN (SELECT id FROM rule)")
    conn.execute("DELETE FROM rule_experiment_member WHERE rule_id NOT IN (SELECT id FROM rule)")
    conn.commit()
    conn.close()

    rule_body = {
        "name": "蔬菜份额续订提醒（M2验收）",
        "conditions": {"logic": "and", "conditions": [
            {"field": "share_type", "op": "eq", "value": "shucai"},
            {"field": "remain_times", "op": "between", "value": [3, 4]},
        ]},
        "exec_time": "09:30", "freq": "daily", "plan_time": "10:00",
        "template": "{会员昵称}您好，我是您的专属客服{客服名}。您的{份额类型}还剩{剩余次数}次（共{总次数}次），{续订权益}，需要续订随时回复我",
        "benefit_text": "本月底前续订立减30元",
        "freq_n_days": 7, "freq_m_times": 2,
        "experiment_enabled": True, "experiment_ratio": 20,
        "priority": 10,
    }
    r = c.post("/api/ops/rules", json=rule_body, headers=admin)
    assert r.status_code == 200, r.text
    rule_id = r.json()["id"]
    results["rule_created"] = True

    r = c.post(f"/api/ops/rules/{rule_id}/preview", headers=admin).json()
    results["preview"] = {k: r[k] for k in ("hit_count", "member_count", "exp_count", "ctrl_count")}
    results["preview_ok"] = r["hit_count"] > 0 and r["exp_count"] + r["ctrl_count"] == r["member_count"]

    r = c.post(f"/api/ops/rules/{rule_id}/run-scan", headers=admin).json()
    results["scan"] = {k: r[k] for k in ("hit_count", "exp_generated", "ctrl_skipped",
                                         "blacklist_skipped", "conflict_skipped", "status")}
    results["scan_ok"] = r["status"] == "ok" and r["exp_generated"] > 0

    r2 = c.post(f"/api/ops/rules/{rule_id}/run-scan", headers=admin).json()
    results["dedup_ok"] = r2["dedup_skipped"] == r["exp_generated"] and r2["exp_generated"] == 0

    conn = sqlite3.connect("data/app.db")
    n_total = conn.execute("SELECT COUNT(*) FROM task").fetchone()[0]
    n_pool = conn.execute("SELECT COUNT(*) FROM task WHERE pool=1 AND status='pending'").fetchone()[0]
    n_assigned = conn.execute(
        "SELECT COUNT(*) FROM task t JOIN operator o ON o.id=t.cs_id "
        "WHERE o.ext_cs_id IS NOT NULL AND t.pool=0 AND t.status='pending'").fetchone()[0]
    conn.close()
    results["tasks"] = {"total": n_total, "pool": n_pool, "assigned_to_synced_cs": n_assigned}
    results["pool_ok"] = n_pool > 0 and n_assigned > 0

    r = c.get("/api/ops/pool?page_size=5", headers=ops).json()
    assert r["items"], "公共池为空"
    pool_task_id = r["items"][0]["id"]
    r = c.post(f"/api/ops/pool/{pool_task_id}/claim", headers=ops)
    results["claim_ok"] = r.status_code == 200

    r = c.get(f"/api/cs/tasks/{pool_task_id}", headers=ops)
    if r.status_code != 200:
        results["detail_error"] = {"status": r.status_code, "body": r.text[:200]}
        results["detail_ok"] = False
    else:
        results["detail_ok"] = "您好" in r.json()["content"]

    r = c.post(f"/api/cs/tasks/{pool_task_id}/copy", headers=ops)
    results["copy_ok"] = r.status_code == 200 and r.json()["copied_at"] is not None

    r = c.post(f"/api/cs/tasks/{pool_task_id}/complete",
               json={"result": "considering"}, headers=ops)
    results["complete_ok"] = r.status_code == 200 and r.json()["status"] == "done"

    conn = sqlite3.connect("data/app.db")
    touch = conn.execute("SELECT result, latency_seconds FROM touch_record WHERE task_id=?",
                         (pool_task_id,)).fetchone()
    conn.close()
    results["touch_ok"] = touch is not None and touch[0] == "considering"

    # 今日小结（用 ops 身份查自己刚完成的）
    r = c.get("/api/cs/summary", headers=ops).json()
    results["summary"] = r

    ok = all(v is True for k, v in results.items() if isinstance(v, bool))
    print(json.dumps({"results": results, "smoke": "PASS" if ok else "FAIL"},
                     ensure_ascii=False, indent=1))
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
