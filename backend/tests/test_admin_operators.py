# -*- coding: utf-8 -*-
"""人员管理 API 单测（方案 B）：账号激活/重置密码/停用启用/越权 403/登录流转。"""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.member import Member
from app.models.operator import CsMemberBinding, Operator


def _admin_headers(client):
    token = client.post("/api/auth/login",
                        json={"name": "t_admin", "password": "password123"}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def _ops_headers(client):
    token = client.post("/api/auth/login",
                        json={"name": "t_ops", "password": "password123"}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


_CS_SEQ = [99100]  # 测试共享 DB，各测试用独立客服避免激活状态串场


def _seed_synced_cs() -> Operator:
    """造一个模拟源同步的客服（password_hash='!' 占位），每个测试独立。"""
    _CS_SEQ[0] += 1
    seq = _CS_SEQ[0]
    with SessionLocal() as db:
        op = db.query(Operator).filter(Operator.name == f"t同步客服{seq}").first()
        if op is None:
            op = Operator(name=f"t同步客服{seq}", role="cs", status="active",
                          ext_cs_id=seq, password_hash="!")
            db.add(op)
            db.commit()
            db.refresh(op)
        return op


def test_ops_forbidden(client, seeded_operators):
    r = client.get("/api/admin/operators", headers=_ops_headers(client))
    assert r.status_code == 403


def test_list_operators_and_activate(client, seeded_operators):
    op = _seed_synced_cs()
    headers = _admin_headers(client)

    r = client.get("/api/admin/operators", headers=headers)
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == op.id)
    assert row["account_ready"] is False  # 占位未激活
    assert row["ext_cs_id"] == op.ext_cs_id

    # 激活（首次设密）→ 登录可用
    r = client.post(f"/api/admin/operators/{op.id}/reset-password",
                    json={"password": "cs123"}, headers=headers)
    assert r.status_code == 200 and r.json()["activated"] is True

    login = client.post("/api/auth/login", json={"name": op.name, "password": "cs123"})
    assert login.status_code == 200
    assert login.json()["operator"]["role"] == "cs"

    # 旧占位密码不可登录
    bad = client.post("/api/auth/login", json={"name": op.name, "password": "!"})
    assert bad.status_code == 401


def test_reset_password_flow(client, seeded_operators):
    op = _seed_synced_cs()
    headers = _admin_headers(client)
    client.post(f"/api/admin/operators/{op.id}/reset-password",
                json={"password": "cs123"}, headers=headers)

    # 重置密码（非首次）→ 新密码生效、旧密码失效；审计记 password_reset
    r = client.post(f"/api/admin/operators/{op.id}/reset-password",
                    json={"password": "newpass66"}, headers=headers)
    assert r.status_code == 200 and r.json()["activated"] is False
    assert client.post("/api/auth/login",
                       json={"name": op.name, "password": "newpass66"}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"name": op.name, "password": "cs123"}).status_code == 401

    # 密码过短 422
    r = client.post(f"/api/admin/operators/{op.id}/reset-password",
                    json={"password": "123"}, headers=headers)
    assert r.status_code == 422


def test_disable_enable_and_task_reassign_note(client, seeded_operators):
    """停用 → 登录态失效（401）+ 返回 BR-06 提示；启用恢复。"""
    op = _seed_synced_cs()
    headers = _admin_headers(client)
    client.post(f"/api/admin/operators/{op.id}/reset-password",
                json={"password": "cs123"}, headers=headers)
    token = client.post("/api/auth/login",
                        json={"name": op.name, "password": "cs123"}).json()["access_token"]
    me_headers = {"Authorization": "Bearer " + token}

    r = client.post(f"/api/admin/operators/{op.id}/status",
                    json={"status": "left"}, headers=headers)
    assert r.status_code == 200
    assert "BR-06" in r.json()["note"]

    # 已停用 → 原 token 立即失效，登录直接 403「账号已停用」
    r = client.get("/api/cs/tasks", headers=me_headers)
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"name": op.name, "password": "cs123"})
    assert r.status_code == 403

    # 启用恢复：登录恢复 + 原 token 可用
    r = client.post(f"/api/admin/operators/{op.id}/status",
                    json={"status": "active"}, headers=headers)
    assert r.status_code == 200 and r.json()["note"] is None
    assert client.post("/api/auth/login",
                       json={"name": op.name, "password": "cs123"}).status_code == 200
    r = client.get("/api/cs/tasks", headers=me_headers)
    assert r.status_code == 200


def test_cannot_disable_self_or_admin(client, seeded_operators):
    headers = _admin_headers(client)
    with SessionLocal() as db:
        admin = db.scalar(select(Operator).where(Operator.name == "t_admin"))
        admin_id = admin.id
        other_admin = Operator(name="t_admin2", role="admin", status="active",
                               password_hash=hash_password("password123"))
        db.add(other_admin)
        db.commit()
        db.refresh(other_admin)
        other_admin_id = other_admin.id
    r = client.post(f"/api/admin/operators/{admin_id}/status",
                    json={"status": "left"}, headers=headers)
    assert r.status_code == 422  # 不能停用自己
    r = client.post(f"/api/admin/operators/{other_admin_id}/status",
                    json={"status": "left"}, headers=headers)
    assert r.status_code == 422  # 超管不允许停用


def test_binding_count_in_list(client, seeded_operators):
    """列表含当前绑定会员数（人员管理页展示用）。"""
    op = _seed_synced_cs()
    with SessionLocal() as db:
        m = Member(ext_member_id=99099, nickname="人员管理测试会员")
        db.add(m)
        db.commit()
        db.refresh(m)
        exists = db.query(CsMemberBinding).filter(
            CsMemberBinding.cs_id == op.id, CsMemberBinding.member_id == m.id).first()
        if exists is None:
            db.add(CsMemberBinding(cs_id=op.id, member_id=m.id,
                                   is_current=True, source="test"))
            db.commit()

    r = client.get("/api/admin/operators", headers=_admin_headers(client))
    row = next(x for x in r.json() if x["id"] == op.id)
    assert row["binding_count"] >= 1
