# -*- coding: utf-8 -*-
"""扫描生成流水线（F4-01）：规则到期 -> 命中求值 -> 分流/黑名单/频控/互斥/去重 -> 落库。

BR 对照：
- BR-02 黑名单不生成任务（在途任务取消由 blacklist API 负责）
- BR-03 去重：uq_task(member, rule, share, cycle_key)，cycle_key=扫描日
- BR-04 频控按会员计数：N 天 <= M 次（同一天多条份额计 1），M<=4、N>=7 硬上限
- BR-09 互斥：同会员+份额+当天最多一条任务；规则按 priority 降序执行，先到先得
- BR-11 分流落库制：hash(member:rule) 首次落 rule_experiment_member，永久不变
- D4 逾期 3 天自动过期；BR-06 离职客服在途任务转公共池
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .evaluator import ConditionError, evaluate_tree, validate_tree
from ..models.member import Blacklist, Member, Tag
from ..models.operator import CsMemberBinding, Operator
from ..models.rule import Rule, RuleExperimentMember, RuleScanLog
from ..models.share import ShareDetail
from ..models.task import Task, TaskStateLog

logger = logging.getLogger("greenos.rules")

FREQ_M_HARD_MAX = 4   # BR-04 硬上限
FREQ_N_HARD_MIN = 7
EXPIRE_DAYS = 3       # D4 默认
INACTIVE_ORDER_STATUSES = (0, 3)  # 删除/完结的份额不参与命中


def assign_group(member_id: int, rule_id: int, ratio: int) -> str:
    """BR-11：hash(member:rule) 稳定分组；ratio=对照组百分比。"""
    digest = hashlib.md5(f"{member_id}:{rule_id}".encode()).hexdigest()
    return "ctrl" if (int(digest[:8], 16) % 100) < ratio else "exp"


def get_or_assign_group(db: Session, rule_id: int, member_id: int, ratio: int) -> str:
    row = db.scalar(select(RuleExperimentMember).where(
        RuleExperimentMember.rule_id == rule_id, RuleExperimentMember.member_id == member_id))
    if row is not None:
        return row.grp
    grp = assign_group(member_id, rule_id, ratio)
    db.add(RuleExperimentMember(rule_id=rule_id, member_id=member_id, grp=grp,
                                assigned_at=datetime.now()))
    db.flush()  # 同事务内后续查询可见（同一会员多份额命中时不撞唯一约束）
    return grp


def _is_due(rule: Rule, now: datetime) -> bool:
    if rule.status != "enabled":
        return False
    today = now.date()
    if rule.start_date and today < rule.start_date:
        return False
    if rule.end_date and today > rule.end_date:
        return False
    if rule.freq == "weekly":
        weekdays = {int(w) for w in (rule.weekdays or "").split(",") if w.strip().isdigit()}
        if now.weekday() not in weekdays:
            return False
    return True


def _scan_done_today(db: Session, rule_id: int, today) -> bool:
    row = db.scalar(select(RuleScanLog.id).where(
        RuleScanLog.rule_id == rule_id,
        func.date(RuleScanLog.scan_at) == today.isoformat()))
    return row is not None

def run_scan(db: Session, rule: Rule, now: Optional[datetime] = None) -> dict:
    """单规则扫描：命中 -> 过滤 -> 落库。返回统计 dict（含 status）。"""
    now = now or datetime.now()
    started = datetime.now()
    stats = {"hit_count": 0, "exp_generated": 0, "ctrl_skipped": 0, "freq_skipped": 0,
             "blacklist_skipped": 0, "dedup_skipped": 0, "conflict_skipped": 0}
    try:
        cycle_key = now.date().isoformat()
        conditions = json.loads(rule.conditions_json)
        validate_tree(conditions)

        # 预载上下文
        blacklist_ids = set(db.scalars(select(Blacklist.member_id).where(Blacklist.is_active.is_(True))))
        binding_map = dict(db.execute(
            select(CsMemberBinding.member_id, CsMemberBinding.cs_id)
            .where(CsMemberBinding.is_current.is_(True))).all())
        tag_map: dict[int, set[str]] = {}
        for mid, key in db.execute(select(Tag.member_id, Tag.tag_key).where(
                Tag.expire_at.is_(None) | (Tag.expire_at > now))):
            tag_map.setdefault(mid, set()).add(key)

        members = {m.id: m for m in db.scalars(select(Member))}

        # 当日已占用：(rule, member, share) 全部规则 today 的任务（去重+BR-09 互斥）
        existing = set(db.execute(select(Task.rule_id, Task.member_id, Task.share_detail_id)
                                  .where(Task.cycle_key == cycle_key)).all())
        occupied = {(m, s) for (_r, m, s) in existing}

        # 命中求值：生效中的份额明细 x 会员
        share_rows = db.execute(
            select(ShareDetail, Member.id)
            .join(Member, Member.id == ShareDetail.member_id)
            .where(or_(ShareDetail.order_status.is_(None),
                       ~ShareDetail.order_status.in_(INACTIVE_ORDER_STATUSES)))
        ).all()

        freq_m = min(int(rule.freq_m_times or 2), FREQ_M_HARD_MAX)
        freq_n = max(int(rule.freq_n_days or 7), FREQ_N_HARD_MIN)
        window_start = now - timedelta(days=freq_n)
        freq_day_cache: dict[int, set] = {}

        plan_time = now.replace(hour=int(rule.plan_time[:2]), minute=int(rule.plan_time[3:5]),
                                second=0, microsecond=0)
        expire_deadline = plan_time + timedelta(days=EXPIRE_DAYS)

        for share, member_id in share_rows:
            member = members.get(member_id)
            if member is None:
                continue
            ctx = {
                "remain_times": share.remain_times,
                "share_type": share.share_type,
                "order_status": share.order_status,
                "good_name": share.good_name,
                "cs_id": binding_map.get(member_id),
                "register_days": ((now - member.register_time).days
                                  if member.register_time else None),
                "tag_keys": tag_map.get(member_id, set()),
            }
            if not evaluate_tree(conditions, ctx):
                continue
            stats["hit_count"] += 1

            if member_id in blacklist_ids:
                stats["blacklist_skipped"] += 1
                continue
            if (rule.id, member_id, share.id) in existing:
                stats["dedup_skipped"] += 1
                continue
            if (member_id, share.id) in occupied:
                stats["conflict_skipped"] += 1  # BR-09：更高优先级规则已占用
                continue
            if rule.experiment_enabled and get_or_assign_group(
                    db, rule.id, member_id, rule.experiment_ratio) == "ctrl":
                stats["ctrl_skipped"] += 1  # F3-12：对照组不生成任务，仅留分组记录
                continue

            # BR-04 频控：按会员计数（同一天多条份额计 1 次）
            days = freq_day_cache.get(member_id)
            if days is None:
                day_rows = db.scalars(select(func.date(Task.plan_time)).where(
                    Task.member_id == member_id,
                    Task.status.in_(["pending", "done"]),
                    Task.plan_time >= window_start)).all()
                days = set(day_rows)
                freq_day_cache[member_id] = days
            if len(days) >= freq_m:
                stats["freq_skipped"] += 1
                continue

            cs_id = binding_map.get(member_id)
            task = Task(rule_id=rule.id, cs_id=cs_id, member_id=member_id,
                        share_detail_id=share.id, plan_time=plan_time,
                        cycle_key=cycle_key, status="pending",
                        expire_deadline=expire_deadline, pool=cs_id is None,
                        remain_times_at_create=share.remain_times)
            db.add(task)
            db.flush()
            db.add(TaskStateLog(task_id=task.id, from_status=None, to_status="pending",
                                operator_id=None, reason=f"rule-scan:{rule.id}"))
            stats["exp_generated"] += 1
            existing.add((rule.id, member_id, share.id))
            occupied.add((member_id, share.id))
            days.add(now.date())

        db.commit()
        stats["status"] = "ok"
        _write_scan_log(db, rule.id, started, stats)
        return stats
    except Exception as exc:
        db.rollback()
        logger.exception("scan rule %s failed", rule.id)
        stats["status"] = "failed"
        stats["error"] = str(exc)
        _write_scan_log(db, rule.id, started, stats)
        return stats


def _write_scan_log(db: Session, rule_id: int, started: datetime, stats: dict) -> None:
    db.add(RuleScanLog(
        rule_id=rule_id, scan_at=started,
        hit_count=stats.get("hit_count", 0), exp_generated=stats.get("exp_generated", 0),
        ctrl_skipped=stats.get("ctrl_skipped", 0), freq_skipped=stats.get("freq_skipped", 0),
        blacklist_skipped=stats.get("blacklist_skipped", 0),
        dedup_skipped=stats.get("dedup_skipped", 0),
        conflict_skipped=stats.get("conflict_skipped", 0),
        status=stats.get("status", "failed"), error=stats.get("error"),
        duration_ms=int((datetime.now() - started).total_seconds() * 1000),
    ))
    db.commit()

def run_due_scans(db: Session, now: Optional[datetime] = None) -> list[dict]:
    """调度入口：扫描当前时刻到期的规则（priority 降序执行，保证 BR-09 仲裁顺序）。

    幂等：同一规则同一天只跑一次（rule_scan_log 判重，重启/重跑不重复生成）。
    单规则失败不阻断其他规则（BR-08 同款思路）。
    """
    now = now or datetime.now()
    hhmm = now.strftime("%H:%M")
    results = []
    rules = db.scalars(select(Rule).where(Rule.status == "enabled")
                       .order_by(Rule.priority.desc(), Rule.id.asc())).all()
    for rule in rules:
        if not _is_due(rule, now) or rule.exec_time != hhmm:
            continue
        if _scan_done_today(db, rule.id, now.date()):
            results.append({"rule_id": rule.id, "rule_name": rule.name, "status": "already_scanned"})
            continue
        stats = run_scan(db, rule, now)
        results.append({"rule_id": rule.id, "rule_name": rule.name, **stats})
    return results


def expire_stale_tasks(db: Session, now: Optional[datetime] = None) -> int:
    """D4：超过计划时间 N 天仍未处理的任务自动过期（BR-05 单向流转 + BR-07 留痕）。"""
    now = now or datetime.now()
    deadline_cutoff = now - timedelta(days=EXPIRE_DAYS)
    stale = db.scalars(select(Task).where(
        Task.status == "pending",
        Task.plan_time.is_not(None),
        Task.plan_time < deadline_cutoff)).all()
    for task in stale:
        task.status = "expired"
        db.add(TaskStateLog(task_id=task.id, from_status="pending", to_status="expired",
                            operator_id=None, reason=f"auto-expire:{EXPIRE_DAYS}d"))
    if stale:
        db.commit()
    return len(stale)


def reassign_inactive_cs_tasks(db: Session) -> int:
    """BR-06：客服离职（status != active）时，其在途任务转公共池，不删除。"""
    rows = db.execute(
        select(Task, Operator.status)
        .join(Operator, Operator.id == Task.cs_id)
        .where(Task.status == "pending", Task.pool.is_(False),
               Operator.status != "active")).all()
    count = 0
    for task, _status in rows:
        task.cs_id = None
        task.pool = True
        db.add(TaskStateLog(task_id=task.id, from_status="pending", to_status="pending",
                            operator_id=None, reason="cs-inactive-to-pool"))
        count += 1
    if count:
        db.commit()
    return count


def reassign_pending_pool_tasks(db: Session) -> dict:
    """一次性补分配（v0.3.6 归属修复遗留面）：把仍 pending 的未认领公共池任务
    按当前绑定（MemberInfo.Staff 三口径）补挂 cs_id。

    只动：status=pending + pool=True + cs_id IS NULL（未被认领）；
    不动：已完成（绩效锁定）/已被认领（处理中）/已过期任务（BR-01 不重排）。
    幂等：重复执行第二次为 0（已补挂的任务不再是 pool=1 且 cs_id NULL）。
    """
    binding_map = dict(db.execute(
        select(CsMemberBinding.member_id, CsMemberBinding.cs_id)
        .where(CsMemberBinding.is_current.is_(True))).all())
    rows = db.scalars(select(Task).where(
        Task.status == "pending", Task.pool.is_(True), Task.cs_id.is_(None))).all()
    reassigned = 0
    no_binding = 0
    for task in rows:
        cs_id = binding_map.get(task.member_id)
        if cs_id is None:
            no_binding += 1  # 会员源系统本无归属，继续留公共池
            continue
        task.cs_id = cs_id
        task.pool = False
        db.add(TaskStateLog(task_id=task.id, from_status="pending", to_status="pending",
                            operator_id=None, reason="binding-fix-reassign"))
        reassigned += 1
    if reassigned:
        db.commit()
    return {"pool_unclaimed": len(rows), "reassigned": reassigned,
            "no_binding_left": no_binding, "status": "ok"}


def preview_hits(db: Session, rule: Rule, now: Optional[datetime] = None,
                 sample_size: int = 10) -> dict:
    """F3-04 命中预览（F3-07 试跑）：不落库，返回命中数/会员数/实验对照组分布/样本。"""
    now = now or datetime.now()
    conditions = json.loads(rule.conditions_json)
    validate_tree(conditions)
    blacklist_ids = set(db.scalars(select(Blacklist.member_id).where(Blacklist.is_active.is_(True))))
    members = {m.id: m for m in db.scalars(select(Member))}
    tag_map: dict[int, set[str]] = {}
    for mid, key in db.execute(select(Tag.member_id, Tag.tag_key).where(
            Tag.expire_at.is_(None) | (Tag.expire_at > now))):
        tag_map.setdefault(mid, set()).add(key)
    share_rows = db.execute(
        select(ShareDetail, Member.id)
        .join(Member, Member.id == ShareDetail.member_id)
        .where(or_(ShareDetail.order_status.is_(None),
                   ~ShareDetail.order_status.in_(INACTIVE_ORDER_STATUSES)))).all()

    hits: list[tuple[int, Any]] = []
    for share, member_id in share_rows:
        member = members.get(member_id)
        if member is None or member_id in blacklist_ids:
            continue
        ctx = {
            "remain_times": share.remain_times, "share_type": share.share_type,
            "order_status": share.order_status, "good_name": share.good_name,
            "cs_id": None, "register_days": ((now - member.register_time).days
                                             if member.register_time else None),
            "tag_keys": tag_map.get(member_id, set()),
        }
        if evaluate_tree(conditions, ctx):
            hits.append((member_id, share.id))

    member_ids = {m for m, _s in hits}
    exp = sum(1 for mid in member_ids
              if assign_group(mid, rule.id, rule.experiment_ratio) == "exp")
    sample = [{"member_id": m, "share_detail_id": s} for m, s in hits[:sample_size]]
    return {"hit_count": len(hits), "member_count": len(member_ids),
            "exp_count": exp, "ctrl_count": len(member_ids) - exp,
            "min_sample_warning": exp < 30, "sample": sample}
