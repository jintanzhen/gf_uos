# -*- coding: utf-8 -*-
"""测试环境：独立 SQLite 文件 + 真实 Alembic 迁移建表 + TestClient。

必须在导入 app 之前设置 DATABASE_URL / JWT_SECRET 环境变量。
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

_TMP = tempfile.mkdtemp(prefix="greenos_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["JWT_SECRET"] = "test-secret"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.operator import Operator  # noqa: E402

_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
command.upgrade(_cfg, "head")


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def seeded_operators() -> dict[str, Operator]:
    """预置 admin / ops / cs 三个账号（密码统一 password123）。"""
    with SessionLocal() as db:
        created = {}
        for role in ("admin", "ops", "cs"):
            exists = db.query(Operator).filter(Operator.name == f"t_{role}").first()
            if exists:
                created[role] = exists
                continue
            op = Operator(
                name=f"t_{role}",
                role=role,
                status="active",
                password_hash=hash_password("password123"),
            )
            db.add(op)
            db.commit()
            db.refresh(op)
            created[role] = op
        return created


def _login(client: TestClient, name: str, password: str = "password123") -> str:
    resp = client.post("/api/auth/login", json={"name": name, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(client, seeded_operators) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, 't_admin')}"}


@pytest.fixture(scope="session")
def ops_headers(client, seeded_operators) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, 't_ops')}"}


@pytest.fixture(scope="session")
def cs_headers(client, seeded_operators) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, 't_cs')}"}


def count_audit(action: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM audit_log WHERE action = :a"), {"a": action}
        ).scalar()
