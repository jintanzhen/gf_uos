# -*- coding: utf-8 -*-
"""调度器占位（ADR-1：APScheduler 内嵌 FastAPI 进程）。

M1 将注册：每日同步任务；M2 注册：规则扫描 + 过期清理；M3：归因回补。
M0 仅启动实例并保留心跳，证明内嵌调度可用。
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("greenos.scheduler")

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _heartbeat() -> None:
    logger.info("scheduler heartbeat: alive")


def _daily_sync() -> None:
    """M1：每日全量同步管线（staff→member→order→share→binding，BR-08 失败不阻断）。"""
    from ..spider.sync import SyncRunning, run_sync

    try:
        results = run_sync("all")
        logger.info("daily sync done: %s", results)
    except SyncRunning as exc:
        logger.warning("daily sync skipped: %s", exc)
    except Exception:
        logger.exception("daily sync crashed")


def _daily_attribution() -> None:
    """M3：续订归因每日回补（F6-04/F6-05，D7：同步拿到新数据后重算窗口内任务）。"""
    from ..core.db import SessionLocal
    from ..rules.attribution import attribute_renewals

    try:
        with SessionLocal() as db:
            stats = attribute_renewals(db)
            logger.info("attribution backfill: %s", stats)
    except Exception:
        logger.exception("attribution backfill crashed")


def _minute_tick() -> None:
    """M2：每分钟 tick —— 规则到期扫描（幂等：规则每日一次）+ 过期清理 + 离职转池。"""
    from ..core.db import SessionLocal
    from ..rules.scanner import expire_stale_tasks, reassign_inactive_cs_tasks, run_due_scans

    try:
        with SessionLocal() as db:
            results = run_due_scans(db)
            for r in results:
                if r.get("status") not in ("already_scanned",):
                    logger.info("scan done: %s", r)
            expired = expire_stale_tasks(db)
            if expired:
                logger.info("auto-expired %d tasks", expired)
            reassign = reassign_inactive_cs_tasks(db)
            if reassign:
                logger.info("reassigned %d tasks to pool (BR-06)", reassign)
    except Exception:
        logger.exception("minute tick failed")


def start_scheduler() -> None:
    if not scheduler.get_job("heartbeat"):
        scheduler.add_job(_heartbeat, "interval", hours=6, id="heartbeat", replace_existing=True)
    if not scheduler.get_job("daily_sync"):
        # 每日 02:30 同步（避开业务高峰；手动重跑走 /api/admin/sync/all/run）
        scheduler.add_job(_daily_sync, "cron", hour=2, minute=30, id="daily_sync",
                          replace_existing=True, max_instances=1)
    if not scheduler.get_job("daily_attribution"):
        # 每日 03:10 续订归因回补（同步完成之后）
        scheduler.add_job(_daily_attribution, "cron", hour=3, minute=10,
                          id="daily_attribution", replace_existing=True, max_instances=1)
    if not scheduler.get_job("minute_tick"):
        # 规则扫描由规则自身 exec_time 决定；tick 每分钟触发一次检查
        scheduler.add_job(_minute_tick, "interval", minutes=1, id="minute_tick",
                          replace_existing=True, max_instances=1)
    if not scheduler.running:
        scheduler.start()
    logger.info("scheduler started (heartbeat + daily_sync@02:30 + minute_tick)")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
