# -*- coding: utf-8 -*-
"""M0 验收用例：登录成败、JWT 身份、角色越权 403 且审计落库。"""
from tests.conftest import count_audit


def test_health_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_ok(client, seeded_operators):
    resp = client.post("/api/auth/login", json={"name": "t_admin", "password": "password123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["operator"]["role"] == "admin"


def test_login_wrong_password_401_and_audited(client):
    before = count_audit("login_failed")
    resp = client.post("/api/auth/login", json={"name": "t_admin", "password": "wrong"})
    assert resp.status_code == 401
    assert count_audit("login_failed") == before + 1


def test_login_unknown_user_401(client):
    resp = client.post("/api/auth/login", json={"name": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_identity(client, cs_headers):
    resp = client.get("/api/auth/me", headers=cs_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "cs"


def test_cs_cannot_access_admin_ping_403_audited(client, cs_headers):
    """BR-10/F5-03：越权 403 且 audit_log 有 access_denied 记录。"""
    before = count_audit("access_denied")
    resp = client.get("/api/admin/ping", headers=cs_headers)
    assert resp.status_code == 403
    assert count_audit("access_denied") == before + 1


def test_cs_cannot_access_ops_ping(client, cs_headers):
    assert client.get("/api/ops/ping", headers=cs_headers).status_code == 403


def test_ops_can_access_ops_ping(client, ops_headers):
    resp = client.get("/api/ops/ping", headers=ops_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "ops"


def test_admin_can_access_ops_ping(client, admin_headers):
    assert client.get("/api/ops/ping", headers=admin_headers).status_code == 200


def test_admin_ping_ok(client, admin_headers):
    assert client.get("/api/admin/ping", headers=admin_headers).status_code == 200


def test_cs_ping_ok(client, cs_headers):
    assert client.get("/api/cs/ping", headers=cs_headers).status_code == 200


def test_bad_token_401(client):
    assert client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    ).status_code == 401
