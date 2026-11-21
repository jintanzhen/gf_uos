# -*- coding: utf-8 -*-
"""迁移可重放幂等验收：upgrade -> downgrade base -> upgrade，表与触发器均应恢复。

在独立临时库上执行（通过 cfg.attributes["database_url"] 覆盖），
避免整库重放摧毁共享测试库中其他测试的数据（历史教训：曾导致全量测试连锁失败）。
"""
import sqlite3
import tempfile

from alembic import command
from alembic.config import Config

from tests.conftest import BACKEND_DIR  # noqa: F401

_EXPECTED_TABLES = {
    "operator", "cs_member_binding", "member", "member_blacklist", "tag",
    "share_detail", "rule", "rule_experiment_member", "rule_scan_log",
    "task", "task_state_log", "touch_record", "audit_log", "sync_log", "spider_cursor",
    "ext_order",
}
_EXPECTED_TRIGGERS = {
    "trg_binding_single_current_insert", "trg_binding_single_current_update",
}


def _objects(db_path: str) -> tuple[set, set]:
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite%' AND name NOT LIKE 'alembic%'"
            )
        }
        triggers = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        return tables, triggers
    finally:
        conn.close()


def test_migration_replay_idempotent():
    tmp = tempfile.mkdtemp(prefix="greenos_replay_")
    db_path = tmp + "/replay.db"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = "sqlite:///" + db_path

    command.upgrade(cfg, "head")
    tables, triggers = _objects(db_path)
    assert tables == _EXPECTED_TABLES, "表集合不符: " + str(tables ^ _EXPECTED_TABLES)
    assert triggers == _EXPECTED_TRIGGERS, "触发器不符: " + str(triggers ^ _EXPECTED_TRIGGERS)

    command.downgrade(cfg, "base")
    tables, _t = _objects(db_path)
    assert not tables, "downgrade 后仍有表: " + str(tables)

    command.upgrade(cfg, "head")
    tables, triggers = _objects(db_path)
    assert tables == _EXPECTED_TABLES, "重放后表集合不符: " + str(tables ^ _EXPECTED_TABLES)
    assert triggers == _EXPECTED_TRIGGERS, "重放后触发器不符: " + str(triggers ^ _EXPECTED_TRIGGERS)
