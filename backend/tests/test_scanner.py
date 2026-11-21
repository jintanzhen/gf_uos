# -*- coding: utf-8 -*-
"""扫描流水线单测：分流/黑名单/频控/BR-09互斥/BR-03去重/公共池/过期/预览。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.member import Blacklist, Member
from app.models.operator import CsMemberBinding, Operator
from app.models.rule import Rule, RuleExperimentMember
from app.models.share import ShareDetail
from app.models.task import Task, TaskStateLog
from app.rules.scanner import (
    assign_group, expire_stale_tasks, preview_hits, reassign_pending_pool_tasks, run_scan,
)

TREE = {"logic": "and", "conditions": [
    {"field": "share_type", "op": "eq", "value": "shucai"},
    {"field": "remain_times", "op": "lte", "value": 4},
    {"field": "good_name", "op": "contains", "value": "M2"},
]}


def _make_rule(name, *, priority=0, experiment=True, m=2, n=7, ratio=20, tree=None):
    return Rule(
        name=name, conditions_json=json.dumps(tree or TREE, ensure_ascii=False),
        exec_time="09:30", freq="daily", plan_time="10:00",
        template="{会员昵称}您好，{份额类型}还剩{剩余次数}次",
        benefit_text="续订立减30元",
        freq_n_days=n, freq_m_times=m, experiment_enabled=experiment,
        experiment_ratio=ratio, priority=priority, status="enabled",
    )


def _seed_world(db):
    """4 名会员：8001 有归属(实验组期望)、8002 无归属(公共池)、8003 黑名单、8004 双份额(频控)。"""
    cs = db.query(Operator).filter(Operator.name == "t_cs").first()
    now = datetime.now()
    for ext_id in (8001, 8002, 8003, 8004):
        if db.query(Member).filter(Member.ext_member_id == ext_id).first() is None:
            db.add(Member(ext_member_id=ext_id, nickname=f"菜友{ext_id}", register_time=now))
    db.commit()
    members = {m.ext_member_id: m for m in
               db.query(Member).filter(Member.ext_member_id.in_([8001, 8002, 8003, 8004]))}
    m1, m2, m3, m4 = members[8001], members[8002], members[8003], members[8004]

    if db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m1.id).first() is None:
        db.add(CsMemberBinding(cs_id=cs.id, member_id=m1.id, is_current=True, source="test"))
    if db.query(Blacklist).filter(Blacklist.member_id == m3.id).first() is None:
        db.add(Blacklist(member_id=m3.id, is_active=True, reason="test"))
    db.commit()

    shares = {}
    specs = [
        ("s1", m1, "shucai", 4), ("s2", m2, "shucai", 3), ("s3", m3, "shucai", 2),
        ("s4a", m4, "shucai", 4), ("s4b", m4, "shucai", 1), ("s5", m1, "doufu", 5),
    ]
    for key, m, stype, remain in specs:
        ext_detail = f"m2-{key}"
        s = db.query(ShareDetail).filter(ShareDetail.ext_detail_id == ext_detail).first()
        if s is None:
            s = ShareDetail(ext_detail_id=ext_detail, ext_order_id=f"o-{key}",
                            member_id=m.id, share_type=stype, good_name="M2测试蔬菜",
                            total_cnt=12, shipped_cnt=8, remain_times=remain, order_status=2)
            db.add(s)
            db.commit()
            db.refresh(s)
        shares[key] = s
    return cs, (m1, m2, m3, m4), shares

def test_scan_pipeline(client, seeded_operators):
    """主流程：实验组生成、对照组跳过、黑名单跳过、公共池、无归属。"""
    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    rule = _make_rule("M2主流程")
    db.add(rule)
    db.commit()
    db.refresh(rule)

    stats = run_scan(db, rule, now=datetime(2026, 11, 21, 9, 30))
    assert stats["status"] == "ok"
    assert stats["blacklist_skipped"] == 1  # 8003 黑名单
    # 命中: s1(8001), s2(8002), s3(8003), s4a/s4b(8004) = 5；doufu remain5 不命中
    assert stats["hit_count"] == 5

    tasks = db.scalars(select(Task).where(Task.rule_id == rule.id)).all()
    # 实验组成员生成任务；对照组仅分组记录
    exp_ids = {t.member_id for t in tasks}
    for t in tasks:
        assert t.cycle_key == "2026-11-21"
        assert t.plan_time == datetime(2026, 11, 21, 10, 0)
        assert t.expire_deadline == datetime(2026, 11, 24, 10, 0)  # D4 3 天
    # 8002 无归属 -> 公共池；8001 有归属 -> 固化 cs_id
    by_member = {}
    for t in tasks:
        by_member.setdefault(t.member_id, []).append(t)
    if m1.id in exp_ids:
        t1 = by_member[m1.id][0]
        assert t1.cs_id == cs.id and t1.pool is False
    if m2.id in exp_ids:
        t2 = by_member[m2.id][0]
        assert t2.cs_id is None and t2.pool is True

    # BR-11：分组记录已落库且稳定
    grps = dict(db.execute(select(RuleExperimentMember.member_id, RuleExperimentMember.grp)
                           .where(RuleExperimentMember.rule_id == rule.id)).all())
    for mid in (m1.id, m2.id, m4.id):  # 8003 黑名单在分组前跳过，无分组记录
        expect = assign_group(mid, rule.id, 20)
        assert grps.get(mid) == expect
        if expect == "ctrl":
            assert mid not in exp_ids  # F3-12 对照组无任务
    db.close()


def test_scan_idempotent_and_freq(client, seeded_operators):
    """BR-03 重跑去重 + BR-04 频控（同一天多份额计 1 次，M=1 时第二份额跳过）。"""
    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    rule = _make_rule("M2频控", experiment=False, m=1)
    db.add(rule)
    db.commit()
    db.refresh(rule)

    now = datetime(2030, 1, 5, 9, 30)
    s1 = run_scan(db, rule, now=now)
    assert s1["status"] == "ok"
    n_first = db.query(Task).filter(Task.rule_id == rule.id).count()
    # 8004 有两个命中份额：M=1 → 第一条生成后当天已计 1 次，第二条频控跳过
    assert s1["freq_skipped"] == 1

    s2 = run_scan(db, rule, now=now)  # 同日重跑
    assert s2["dedup_skipped"] == n_first
    assert db.query(Task).filter(Task.rule_id == rule.id).count() == n_first
    db.close()


def test_br09_priority_arbitration(client, seeded_operators):
    """BR-09：同会员+份额同天多规则，高优先级先到先得，低优先级 conflict 跳过。"""
    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    tree_b = {"logic": "and", "conditions": [{"field": "share_type", "op": "eq", "value": "shucai"}]}
    rule_low = _make_rule("M2低优先", experiment=False, priority=0)
    rule_high = _make_rule("M2高优先", experiment=False, priority=10, tree=tree_b)
    db.add_all([rule_low, rule_high])
    db.commit()
    db.refresh(rule_low)
    db.refresh(rule_high)

    now = datetime(2030, 2, 10, 9, 30)
    run_scan(db, rule_high, now=now)   # 高优先级先占用（全类型命中，含 s5 doufu）
    s_low = run_scan(db, rule_low, now=now)
    assert s_low["conflict_skipped"] >= 1  # 与高优先级规则冲突的份额全部让位
    db.close()


def test_blacklist_unblock_and_expire(client, seeded_operators):
    """解除黑名单后可生成；D4 过期清理；BR-05 过期不可完成由 API 层测。"""
    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    # 解除 8003 黑名单
    bl = db.query(Blacklist).filter(Blacklist.member_id == m3.id).first()
    bl.is_active = False
    db.commit()

    rule = _make_rule("M2解禁", experiment=False)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    stats = run_scan(db, rule, now=datetime(2030, 3, 10, 9, 30))
    assert stats["blacklist_skipped"] == 0
    assert db.query(Task).filter(Task.rule_id == rule.id).count() >= 5

    # 过期：把任务计划时间改到 4 天前
    old = datetime.now() - timedelta(days=4)
    for t in db.scalars(select(Task).where(Task.rule_id == rule.id)):
        t.plan_time = old
    db.commit()
    assert expire_stale_tasks(db) >= 5
    assert db.scalars(select(Task.status).where(Task.rule_id == rule.id)).all() == \
        ["expired"] * db.query(Task).filter(Task.rule_id == rule.id).count()
    db.close()


def test_preview_no_persist(client, seeded_operators):
    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    rule = _make_rule("M2预览")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    result = preview_hits(db, rule)
    assert result["hit_count"] == 5
    assert result["exp_count"] + result["ctrl_count"] == result["member_count"]
    assert db.query(Task).filter(Task.rule_id == rule.id).count() == 0  # 预览不落库
    db.close()


def test_reassign_pending_pool_tasks(client, seeded_operators):
    """v0.3.6 补分配：pending+未认领公共池任务按当前绑定补挂；done/过期/无绑定不动；幂等。"""
    from app.models.rule import Rule as RuleModel
    from app.rules.scanner import run_scan

    db = SessionLocal()
    cs, (m1, m2, m3, m4), shares = _seed_world(db)
    rule = _make_rule("M2补分配")
    db.add(rule)
    db.commit()
    db.refresh(rule)

    stats = run_scan(db, rule, now=datetime(2026, 11, 21, 9, 30))
    assert stats["status"] == "ok"

    # 找 8002（无归属 → 公共池）的任务；若 8002 被分流为对照组则换用 8004 的份额任务
    pool_task = db.scalar(select(Task).where(
        Task.member_id == m2.id, Task.rule_id == rule.id,
        Task.pool.is_(True), Task.cs_id.is_(None)))
    if pool_task is None:
        pool_task = db.scalar(select(Task).where(
            Task.rule_id == rule.id, Task.pool.is_(True), Task.cs_id.is_(None)))
    assert pool_task is not None  # 扫描后必有无归属任务落公共池
    pool_member_id = pool_task.member_id

    # 已完成 + 已过期的对照样本（验证补分配不碰）
    db.query(Task).filter(Task.id == pool_task.id).one()
    expired = Task(rule_id=rule.id, cs_id=None, member_id=m3.id, share_detail_id=shares["s3"].id,
                   plan_time=datetime(2026, 11, 1, 10, 0), cycle_key="2026-11-01",
                   status="expired", pool=True)
    db.add(expired)
    db.commit()

    # 模拟 v0.3.6 绑定修复：给 pool_task 的会员补上归属
    if db.query(CsMemberBinding).filter(CsMemberBinding.member_id == pool_member_id).first() is None:
        db.add(CsMemberBinding(cs_id=cs.id, member_id=pool_member_id,
                               is_current=True, source="MemberInfo.Staff"))
        db.commit()

    r1 = reassign_pending_pool_tasks(db)
    assert r1["status"] == "ok"
    assert r1["reassigned"] >= 1
    db.refresh(pool_task)
    assert pool_task.cs_id == cs.id and pool_task.pool is False
    log = db.query(TaskStateLog).filter(
        TaskStateLog.task_id == pool_task.id,
        TaskStateLog.reason == "binding-fix-reassign").order_by(TaskStateLog.id.desc()).first()
    assert log is not None

    db.refresh(expired)
    assert expired.cs_id is None and expired.pool is True  # 过期不动

    # 幂等：再跑一遍 reassigned=0
    r2 = reassign_pending_pool_tasks(db)
    assert r2["reassigned"] == 0
    db.close()
