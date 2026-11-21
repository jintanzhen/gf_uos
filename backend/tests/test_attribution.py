# -*- coding: utf-8 -*-
"""M3 归因引擎与效果看板单测：三信号（D3）/窗口边界/对照组基线/历史重算幂等。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.member import Member
from app.models.order import ExtOrder
from app.models.rule import Rule, RuleExperimentMember
from app.models.share import ShareDetail
from app.models.task import Task
from app.rules.attribution import attribute_renewals

_next = [8200]


def _seed_renewal_world(db):
    """4 个已完成任务：信号①新订单 / 信号③MatchOrder / 信号②剩余回升 / 窗口外。"""
    _next[0] += 10
    base = _next[0]
    now = datetime.now()
    rule = Rule(name=f"M3归因{base}", conditions_json=json.dumps(
        {"logic": "and", "conditions": [{"field": "share_type", "op": "eq", "value": "shucai"}]},
        ensure_ascii=False), exec_time="09:30", freq="daily", plan_time="10:00",
        template="{会员昵称}", attribution_days=30, experiment_enabled=True,
        experiment_ratio=0, status="enabled")
    db.add(rule)
    db.commit()
    db.refresh(rule)

    specs = []  # (offset, remain_snapshot, remain_now, new_order, match_id)
    for i in range(4):
        m = Member(ext_member_id=base + i, nickname=f"归因会员{i}", register_time=now)
        db.add(m)
        db.commit()
        db.refresh(m)
        s = ShareDetail(ext_detail_id=f"m3-{base}-{i}", ext_order_id=f"o-{base}-{i}",
                        member_id=m.id, share_type="shucai", good_name="M3蔬菜",
                        total_cnt=12, shipped_cnt=8, remain_times=4, order_status=2)
        db.add(s)
        db.commit()
        db.refresh(s)
        specs.append((m, s))
    return rule, specs


def _make_task(db, rule, member, share, *, completed_days_ago, remain_snapshot=4):
    t = Task(rule_id=rule.id, cs_id=None, member_id=member.id, share_detail_id=share.id,
             plan_time=datetime.now() - timedelta(days=completed_days_ago + 1),
             cycle_key=f"m3-{member.ext_member_id}", status="done",
             completed_at=datetime.now() - timedelta(days=completed_days_ago),
             remain_times_at_create=remain_snapshot)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _add_ext_order(db, ext_mem_id, *, fen_e=True, days_after_completed=2, match_id=None,
                   base_id):
    e = ExtOrder(ext_order_id=f"eo-{base_id}-{ext_mem_id}-{days_after_completed}",
                 ext_mem_id=ext_mem_id, order_type="FenE" if fen_e else "SanDan",
                 order_status=2,
                 created_at=datetime.utcnow() - timedelta(days=30) + timedelta(days=days_after_completed + 28),
                 match_order_id=match_id)
    # created_at = utcnow - 2days + 微调：保证落在 completed_at+2d 附近窗口内
    e.created_at = datetime.utcnow() - timedelta(days=2)
    db.add(e)
    db.commit()
    return e

def test_three_signals_and_window(client, seeded_operators):
    """信号①新FenE订单 / 信号③MatchOrder / 信号②剩余回升；窗口外任务关闭。"""
    db = SessionLocal()
    rule, specs = _seed_renewal_world(db)
    m1, s1 = specs[0]
    m2, s2 = specs[1]
    m3, s3 = specs[2]
    m4, s4 = specs[3]

    t1 = _make_task(db, rule, m1, s1, completed_days_ago=10)
    t2 = _make_task(db, rule, m2, s2, completed_days_ago=10)
    t3 = _make_task(db, rule, m3, s3, completed_days_ago=10)
    t4 = _make_task(db, rule, m4, s4, completed_days_ago=40)  # 30 天窗口外

    _add_ext_order(db, m1.ext_member_id, base_id=rule.id)                       # 信号①
    _add_ext_order(db, m2.ext_member_id, base_id=rule.id, match_id="prev-oid")  # 信号③
    s3.remain_times = 6  # 信号②：剩余次数回升（无新订单）
    db.commit()

    stats = attribute_renewals(db)
    assert stats["status"] == "ok"
    db.refresh(t1); db.refresh(t2); db.refresh(t3); db.refresh(t4)
    assert t1.renew_signal == "new_order"
    assert t2.renew_signal == "match_order"
    assert t3.renew_signal == "remain_rebound"
    assert t4.renew_detected_at is None and t4.renew_window_closed is True  # 窗口外关闭
    assert t1.renew_ext_order_id is not None
    db.close()


def test_recompute_idempotent(client, seeded_operators):
    """F6-05 历史重算幂等：重算前后指标一致（验收要点）。"""
    db = SessionLocal()
    rule, specs = _seed_renewal_world(db)
    m1, s1 = specs[0]
    _make_task(db, rule, m1, s1, completed_days_ago=10)
    _add_ext_order(db, m1.ext_member_id, base_id=rule.id)

    attribute_renewals(db)
    r1 = db.scalar(select(Task.renew_signal).where(Task.member_id == m1.id))
    n1 = db.query(Task).filter(Task.rule_id == rule.id, Task.renew_detected_at.is_not(None)).count()

    stats = attribute_renewals(db, rule_id=rule.id, recompute=True)
    r2 = db.scalar(select(Task.renew_signal).where(Task.member_id == m1.id))
    n2 = db.query(Task).filter(Task.rule_id == rule.id, Task.renew_detected_at.is_not(None)).count()
    assert r1 == r2 == "new_order"
    assert n1 == n2 == 1
    assert stats["detected"] == 1
    db.close()


def test_experiment_report_and_baseline(client, ops_headers, seeded_operators):
    """F6-02 实验对比：实验组续订率 vs 对照组基线（对照组自行续订只进基线）。"""
    db = SessionLocal()
    rule, specs = _seed_renewal_world(db)
    m1, s1 = specs[0]
    m2, s2 = specs[1]
    # 实验组：任务完成 + 新订单归因
    t1 = _make_task(db, rule, m1, s1, completed_days_ago=10)
    _add_ext_order(db, m1.ext_member_id, base_id=rule.id)
    # 对照组：无任务，仅分流记录 + 窗口内自行续订
    db.add(RuleExperimentMember(rule_id=rule.id, member_id=m2.id, grp="ctrl",
                                assigned_at=datetime.now() - timedelta(days=5)))
    db.commit()
    _add_ext_order(db, m2.ext_member_id, base_id=rule.id + 5000)
    attribute_renewals(db)

    r = client.get(f"/api/ops/reports/experiment/{rule.id}", headers=ops_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exp"]["generated"] == 1 and body["exp"]["done"] == 1
    assert body["exp"]["renew_rate_of_done"] == 1.0
    assert body["exp"]["signal_distribution"] == {"new_order": 1}
    assert body["ctrl"]["members"] == 1 and body["ctrl"]["renewals"] == 1
    assert body["ctrl"]["renew_rate"] == 1.0
    assert body["diff"] == 0.0  # 都续订了 → 增量为 0（基线不冒充效果）
    assert body["conclusion_reliable"] is False  # 样本 < 30
    db.close()


def test_overview_and_ranking(client, ops_headers, seeded_operators):
    db = SessionLocal()
    rule, specs = _seed_renewal_world(db)
    m1, s1 = specs[0]
    _make_task(db, rule, m1, s1, completed_days_ago=3)
    attribute_renewals(db)
    db.close()

    r = client.get(f"/api/ops/reports/overview?rule_id={rule.id}", headers=ops_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] == 1 and body["done"] == 1
    assert body["completion_rate"] == 1.0

    r = client.get("/api/ops/reports/rules-ranking", headers=ops_headers)
    assert r.status_code == 200
    assert any(x["rule_id"] == rule.id for x in r.json())

    # 历史重算 API
    r = client.post("/api/ops/reports/recompute", json={"rule_id": rule.id}, headers=ops_headers)
    assert r.status_code == 200 and r.json()["status"] == "ok"
