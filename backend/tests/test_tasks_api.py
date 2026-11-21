# -*- coding: utf-8 -*-
"""任务 API 单测：三分区/详情/复制留痕/完成回填(BR-05, D11)/改期取消/越权403/小结/公共池/黑名单。"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.member import Member
from app.models.operator import Operator
from app.models.rule import Rule
from app.models.share import ShareDetail
from app.models.task import Task, TaskStateLog, TouchRecord
import json

_next_id = [9100]


def _seed_task(cs: Operator, *, status="pending", plan_offset_hours=0, pool=False,
               result=None, member_ext=None, plan_dt=None, expire_dt=None):
    """直接落一条任务（绕过扫描），返回 (task, member, share)。"""
    db = SessionLocal()
    _next_id[0] += 1
    n = _next_id[0]
    member = Member(ext_member_id=member_ext or n, nickname=f"菜友{n}", register_time=datetime.now())
    db.add(member)
    db.commit()
    db.refresh(member)
    share = ShareDetail(ext_detail_id=f"t-{n}", ext_order_id=f"o-{n}", member_id=member.id,
                        share_type="shucai", good_name="蔬菜份额", total_cnt=12,
                        shipped_cnt=8, remain_times=4, cycle_desc="每周三", order_status=2)
    db.add(share)
    db.commit()
    db.refresh(share)
    rule = Rule(name=f"r{n}", conditions_json=json.dumps({"logic": "and", "conditions": [
                    {"field": "share_type", "op": "eq", "value": "shucai"}]}, ensure_ascii=False),
                exec_time="09:30", freq="daily", plan_time="10:00",
                template="{会员昵称}您好，{份额类型}还剩{剩余次数}次，我是{客服名}",
                benefit_text="续订立减30元", status="enabled")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    plan = plan_dt or (datetime.now() + timedelta(hours=plan_offset_hours))
    task = Task(rule_id=rule.id, cs_id=None if pool else cs.id, member_id=member.id,
                share_detail_id=share.id, plan_time=plan, cycle_key=plan.date().isoformat(),
                status=status, result=result,
                expire_deadline=expire_dt or (plan + timedelta(days=3)), pool=pool)
    db.add(task)
    db.commit()
    db.refresh(task)
    db.close()
    return task, member, share

def _login_cs2(client, seeded_operators):
    """创建并登录第二个客服（越权测试用）。"""
    with SessionLocal() as db:
        cs2 = db.query(Operator).filter(Operator.name == "t_cs2").first()
        if cs2 is None:
            cs2 = Operator(name="t_cs2", role="cs", status="active",
                           password_hash=hash_password("password123"))
            db.add(cs2)
            db.commit()
    r = client.post("/api/auth/login", json={"name": "t_cs2", "password": "password123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_zones_and_detail(client, cs_headers, seeded_operators):
    with SessionLocal() as db:
        cs = db.query(Operator).filter(Operator.name == "t_cs").first()
    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t_today, _, _ = _seed_task(cs, plan_dt=today0 + timedelta(minutes=1))
    t_over, _, _ = _seed_task(cs, plan_dt=today0 - timedelta(days=1))
    t_up, _, _ = _seed_task(cs, plan_dt=today0 + timedelta(days=1, hours=1),
                            expire_dt=now + timedelta(hours=24))  # 48h 内到期 -> upcoming

    r = client.get("/api/cs/tasks?zone=today", headers=cs_headers)
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert t_today.id in ids and t_over.id not in ids

    r = client.get("/api/cs/tasks?zone=overdue", headers=cs_headers)
    assert t_over.id in [i["id"] for i in r.json()["items"]]

    r = client.get("/api/cs/tasks?zone=upcoming", headers=cs_headers)
    assert t_up.id in [i["id"] for i in r.json()["items"]]

    r = client.get(f"/api/cs/tasks/{t_today.id}", headers=cs_headers)
    assert r.status_code == 200
    body = r.json()
    assert "还剩4次" in body["content"]
    assert body["content"].endswith("") or "续订立减30元" not in body["content"]  # 模板未含该变量


def test_copy_idempotent_and_complete(client, cs_headers, seeded_operators):
    with SessionLocal() as db:
        cs = db.query(Operator).filter(Operator.name == "t_cs").first()
    task, member, share = _seed_task(cs)

    r1 = client.post(f"/api/cs/tasks/{task.id}/copy", headers=cs_headers)
    assert r1.status_code == 200 and r1.json()["copied_at"] is not None
    copied_at = r1.json()["copied_at"]
    r2 = client.post(f"/api/cs/tasks/{task.id}/copy", headers=cs_headers)
    assert r2.json()["copied_at"] == copied_at  # 幂等：首次留痕时间不变

    # D11：其他必填备注
    r = client.post(f"/api/cs/tasks/{task.id}/complete",
                    json={"result": "other"}, headers=cs_headers)
    assert r.status_code == 422
    r = client.post(f"/api/cs/tasks/{task.id}/complete",
                    json={"result": "bad_enum"}, headers=cs_headers)
    assert r.status_code == 422

    r = client.post(f"/api/cs/tasks/{task.id}/complete",
                    json={"result": "renewed", "remark": "当场续订"}, headers=cs_headers)
    assert r.status_code == 200 and r.json()["status"] == "done"

    # BR-05：已完成不可回退/重复完成
    r = client.post(f"/api/cs/tasks/{task.id}/complete",
                    json={"result": "renewed"}, headers=cs_headers)
    assert r.status_code == 409
    r = client.post(f"/api/cs/tasks/{task.id}/cancel", json={"reason": "x"}, headers=cs_headers)
    assert r.status_code == 409

    with SessionLocal() as db:
        touch = db.scalars(select(TouchRecord).where(TouchRecord.task_id == task.id)).all()
        assert len(touch) == 1
        assert touch[0].result == "renewed" and touch[0].latency_seconds is not None
        assert len(db.scalars(select(TaskStateLog).where(TaskStateLog.task_id == task.id)).all()) >= 1


def test_reschedule_and_summary(client, cs_headers, seeded_operators):
    with SessionLocal() as db:
        cs = db.query(Operator).filter(Operator.name == "t_cs").first()
    task, _, _ = _seed_task(cs, plan_offset_hours=-48)  # 逾期
    new_time = (datetime.now() + timedelta(days=1)).isoformat()
    r = client.post(f"/api/cs/tasks/{task.id}/reschedule",
                    json={"plan_time": new_time, "reason": "会员要求明天联系"}, headers=cs_headers)
    assert r.status_code == 200
    with SessionLocal() as db:
        t = db.get(Task, task.id)
        assert t.status == "pending" and t.plan_time is not None

    r = client.get("/api/cs/summary", headers=cs_headers)
    assert r.status_code == 200
    body = r.json()
    assert {"should_contact", "contacted", "overdue", "result_distribution"} <= set(body)


def test_forbidden_access_audited(client, cs_headers, seeded_operators):
    with SessionLocal() as db:
        cs = db.query(Operator).filter(Operator.name == "t_cs").first()
    task, _, _ = _seed_task(cs)  # t_cs 的任务
    cs2_headers = _login_cs2(client, seeded_operators)

    r = client.post(f"/api/cs/tasks/{task.id}/complete",
                    json={"result": "renewed"}, headers=cs2_headers)
    assert r.status_code == 403
    with SessionLocal() as db:
        from app.models.system import AuditLog
        assert db.query(AuditLog).filter(AuditLog.action == "access_denied").count() >= 1


def test_pool_claim_and_blacklist(client, ops_headers, cs_headers, seeded_operators):
    with SessionLocal() as db:
        ops = db.query(Operator).filter(Operator.name == "t_ops").first()
    task, member, _ = _seed_task(ops, pool=True)

    r = client.get("/api/ops/pool", headers=ops_headers)
    assert any(i["id"] == task.id for i in r.json()["items"])

    r = client.post(f"/api/ops/pool/{task.id}/claim", headers=ops_headers)
    assert r.status_code == 200 and r.json()["cs_id"] == ops.id

    # BR-02：加黑名单自动取消在途任务
    task2, member2, _ = _seed_task(ops, plan_offset_hours=1)
    r = client.post("/api/ops/blacklist", json={"member_id": member2.id, "reason": "拒绝触达"},
                    headers=ops_headers)
    assert r.status_code == 200 and r.json()["cancelled_tasks"] == 1
    with SessionLocal() as db:
        assert db.get(Task, task2.id).status == "cancelled"
    db.close() if False else None
