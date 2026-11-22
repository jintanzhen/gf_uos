# -*- coding: utf-8 -*-
"""标签体系测试（F2-03 系统标签四口径 / F2-04 人工标签）。

ID 段：会员 7101+（与其他测试隔离），共享 session DB，计数断言用 >=。
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.member import Member, Tag
from app.models.operator import CsMemberBinding, Operator
from app.models.order import ExtOrder
from app.models.share import ShareDetail
from app.tags.service import active_tags_of, compute_system_tags

NOW = datetime(2026, 11, 22, 10, 0)


def _ensure_member(db, ext_id: int, register_time=None) -> Member:
    m = db.query(Member).filter(Member.ext_member_id == ext_id).first()
    if m is None:
        m = Member(ext_member_id=ext_id, nickname=f"标签会员{ext_id}",
                   register_time=register_time)
        db.add(m)
        db.commit()
        db.refresh(m)
    elif register_time is not None and m.register_time is None:
        m.register_time = register_time
        db.commit()
        db.refresh(m)
    return m


def _seed_tag_world(db):
    """五个会员覆盖四口径：
    7101 剩3次(share_low) + 新注册(new_member)
    7102 有消费最高(high_value) + 上月下单(silent)
    7103 消费第二(high_value)
    7104 无消费无份额 + 注册31天前(silent)
    7105 消费第三但只进 Top2 之外（默认 20% × 3 人 → ceil 1 人？3×0.2=0.6→max(1,0)=1 → 只有 7102）
    """
    reg_new = NOW - timedelta(days=3)
    reg_old = NOW - timedelta(days=31)
    m1 = _ensure_member(db, 7101, reg_new)
    m2 = _ensure_member(db, 7102, reg_old)
    m3 = _ensure_member(db, 7103, reg_old)
    m4 = _ensure_member(db, 7104, reg_old)
    m5 = _ensure_member(db, 7105, reg_old)

    def _share(member, remain, status=None):
        exists = db.query(ShareDetail).filter(
            ShareDetail.member_id == member.id,
            ShareDetail.ext_detail_id == f"tag-{member.ext_member_id}-{remain}").first()
        if exists is None:
            db.add(ShareDetail(member_id=member.id, ext_detail_id=f"tag-{member.ext_member_id}-{remain}",
                               share_type="shucai", good_name="标签测试菜", remain_times=remain,
                               order_status=status))
        return member

    _share(m1, 3)
    _share(m1, 8)

    def _order(member, ext_id: str, total, pay_time, mem_ext=None):
        exists = db.query(ExtOrder).filter(ExtOrder.ext_order_id == ext_id).first()
        if exists is None:
            db.add(ExtOrder(ext_order_id=ext_id, ext_mem_id=member.ext_member_id,
                            order_type="FenE", total_price=total, pay_time=pay_time,
                            modify_date=pay_time))
        return member

    last_month = NOW - timedelta(days=40)
    _order(m2, "tag-o1", 5000.0, NOW - timedelta(days=2))     # 高消费 + 2天前下单（不静默）
    _order(m3, "tag-o2", 1500.0, last_month)                  # 静默 + 第二消费
    _order(m5, "tag-o3", 300.0, NOW - timedelta(days=5))      # 第三消费
    db.commit()
    return m1, m2, m3, m4, m5


def test_system_tags_four_rules(client, seeded_operators):
    """F2-03 四口径：share_low / new_member / silent / high_value（Top20%）。"""
    db = SessionLocal()
    m1, m2, m3, m4, _m5 = _seed_tag_world(db)

    stats = compute_system_tags(db, now=NOW)
    assert stats["status"] == "ok"

    keys = lambda mid: {t.tag_key for t in active_tags_of(db, mid)}
    # 7101：剩3次 → share_low（value 剩3次）+ 注册3天 → new_member
    assert keys(m1.id) == {"share_low", "new_member"}
    low = next(t for t in active_tags_of(db, m1.id) if t.tag_key == "share_low")
    assert low.tag_value == "剩3次"
    # 7102：累计 5000 最高 → high_value；2 天前下单 → 不静默；注册31天 → 不新
    assert keys(m2.id) == {"high_value"}
    # 7103：40 天未下单 → silent；消费 1500
    assert "silent" in keys(m3.id)
    silent = next(t for t in active_tags_of(db, m3.id) if t.tag_key == "silent")
    assert "40天未下单" in silent.tag_value
    # 7104：无单无份额 + 注册31天 → silent（注册时间兜底）
    assert keys(m4.id) == {"silent"}
    # 高价值 Top20%：3 个有消费会员 × 0.2 = 0.6 → max(1, int) = 1 人（7102）
    hv = [t for t in db.scalars(select(Tag).where(
        Tag.tag_type == "sys", Tag.tag_key == "high_value")).all()]
    assert len(hv) == 1 and hv[0].member_id == m2.id
    db.close()


def test_system_tags_idempotent_and_manual_untouched(client, seeded_operators):
    """重算幂等（sys 全清重插，计数不变）；manual 标签不受重算影响。"""
    db = SessionLocal()
    m1, _m2, _m3, _m4, _m5 = _seed_tag_world(db)
    compute_system_tags(db, now=NOW)

    db.add(Tag(member_id=m1.id, tag_type="manual", tag_key="价格敏感", created_by=None))
    db.commit()
    r1 = compute_system_tags(db, now=NOW)
    manual = db.scalars(select(Tag).where(
        Tag.member_id == m1.id, Tag.tag_type == "manual")).all()
    assert len(manual) == 1 and manual[0].tag_key == "价格敏感"
    r2 = compute_system_tags(db, now=NOW)
    sys1 = {t.tag_key for t in db.scalars(select(Tag).where(
        Tag.member_id == m1.id, Tag.tag_type == "sys")).all()}
    assert r1["share_low"] == r2["share_low"]
    assert sys1 == {"share_low", "new_member"}
    db.close()


def test_manual_tag_api_permissions_and_audit(client, seeded_operators, ops_headers,
                                              cs_headers, admin_headers):
    """打标/删标 + cs 仅限本人名下（404）+ 审计留痕 + 词表接口。"""
    db = SessionLocal()
    m1, _m2, _m3, _m4, _m5 = _seed_tag_world(db)
    # t_cs 名下绑一个会员用于打标
    from tests.conftest import count_audit
    cs_op = db.query(Operator).filter(Operator.name == "t_cs").first()
    if db.query(CsMemberBinding).filter(
            CsMemberBinding.cs_id == cs_op.id, CsMemberBinding.member_id == m1.id).first() is None:
        db.add(CsMemberBinding(cs_id=cs_op.id, member_id=m1.id, is_current=True, source="test"))
    db.commit()
    member_id = m1.id
    db.close()

    from fastapi.testclient import TestClient

    # cs 给自己名下会员打标（词表标签 + 带到期）
    resp = client.post(f"/api/cs/members/{member_id}/tags",
                       json={"tag_key": "只收微信"}, headers=cs_headers)
    assert resp.status_code == 200, resp.text
    tag_id = resp.json()["id"]
    resp2 = client.post(f"/api/cs/members/{member_id}/tags",
                        json={"tag_key": "勿扰", "expire_at": "2026-12-31"}, headers=cs_headers)
    assert resp2.status_code == 200

    # 重复打同名 → 409
    resp_dup = client.post(f"/api/cs/members/{member_id}/tags",
                           json={"tag_key": "只收微信"}, headers=cs_headers)
    assert resp_dup.status_code == 409

    # cs 给非名下会员打标（7102 未绑给 t_cs）→ 404
    db = SessionLocal()
    other = db.query(Member).filter(Member.ext_member_id == 7102).first()
    other_id = other.id
    db.close()
    resp_404 = client.post(f"/api/cs/members/{other_id}/tags",
                           json={"tag_key": "越权"}, headers=cs_headers)
    assert resp_404.status_code == 404

    # 详情接口带 tags（cs 视角）
    detail = client.get(f"/api/cs/members/{member_id}", headers=cs_headers).json()
    tag_keys = {t["tag_key"] for t in detail["tags"]}
    assert {"只收微信", "勿扰", "share_low", "new_member"} <= tag_keys

    # 审计留痕
    assert count_audit("manual_tag_added") >= 2

    # 词表接口（含刚打的标签）
    keys = client.get("/api/ops/tags/keys", headers=ops_headers).json()
    assert "只收微信" in keys and "勿扰" in keys

    # cs 删除本人打的标签
    resp_del = client.delete(f"/api/cs/tags/{tag_id}", headers=cs_headers)
    assert resp_del.status_code == 200
    assert count_audit("manual_tag_deleted") >= 1

    # ops 给任意会员打标并删除
    resp_ops = client.post(f"/api/ops/members/{member_id}/tags",
                           json={"tag_key": "运营备注"}, headers=ops_headers)
    assert resp_ops.status_code == 200
    ops_tag_id = resp_ops.json()["id"]
    # cs 不能删别人打的标签 → 404
    resp_cs_del = client.delete(f"/api/cs/tags/{ops_tag_id}", headers=cs_headers)
    assert resp_cs_del.status_code == 404
    # ops 可删
    resp_ops_del = client.delete(f"/api/ops/tags/{ops_tag_id}", headers=ops_headers)
    assert resp_ops_del.status_code == 200

    # 手动重算端点
    resp_rc = client.post("/api/ops/tags/recompute", headers=admin_headers)
    assert resp_rc.status_code == 200 and resp_rc.json()["status"] == "ok"
