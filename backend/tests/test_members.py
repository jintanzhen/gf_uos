# -*- coding: utf-8 -*-
"""M1 会员 API 测试：BR-10 归属隔离 + 运营全量检索。"""
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.member import Member
from app.models.operator import CsMemberBinding, Operator
from app.models.share import ShareDetail


def _seed_binding_data():
    """两位客服各绑定一名会员，各持一份份额。"""
    with SessionLocal() as db:
        cs2 = db.query(Operator).filter(Operator.name == "t_cs2").first()
        if cs2 is None:
            cs2 = Operator(name="t_cs2", role="cs", status="active",
                           password_hash=hash_password("password123"))
            db.add(cs2)
            db.commit()
            db.refresh(cs2)
        cs1 = db.query(Operator).filter(Operator.name == "t_cs").first()

        members = {}
        for ext_id in (7001, 7002):
            m = db.query(Member).filter(Member.ext_member_id == ext_id).first()
            if m is None:
                m = Member(ext_member_id=ext_id, real_name=f"会员{ext_id}", mobile=f"139{ext_id:08d}")
                db.add(m)
                db.commit()
                db.refresh(m)
            members[ext_id] = m

        for cs, m in ((cs1, members[7001]), (cs2, members[7002])):
            exists = db.query(CsMemberBinding).filter(
                CsMemberBinding.cs_id == cs.id, CsMemberBinding.member_id == m.id
            ).first()
            if exists is None:
                db.add(CsMemberBinding(cs_id=cs.id, member_id=m.id, is_current=True, source="test"))

        if db.query(ShareDetail).filter(ShareDetail.ext_detail_id == "t-detail-1").first() is None:
            db.add(ShareDetail(
                ext_detail_id="t-detail-1", member_id=members[7001].id,
                ext_order_id="t-order-1", share_type="shucai", good_name="蔬菜份额",
                total_cnt=12, shipped_cnt=8, remain_times=4, order_status=2,
            ))
        db.commit()
        return members


def test_cs_sees_only_own_members(client, cs_headers):
    members = _seed_binding_data()
    resp = client.get("/api/cs/members", headers=cs_headers)
    assert resp.status_code == 200
    ids = [i["ext_member_id"] for i in resp.json()["items"]]
    assert 7001 in ids
    assert 7002 not in ids  # BR-10：别人的会员不可见
    mine = next(i for i in resp.json()["items"] if i["ext_member_id"] == 7001)
    assert mine["share_count"] == 1 and mine["min_remain_times"] == 4


def test_cs_cannot_access_others_member_detail(client, cs_headers):
    members = _seed_binding_data()
    assert client.get(f"/api/cs/members/{members[7002].id}", headers=cs_headers).status_code == 404
    resp = client.get(f"/api/cs/members/{members[7001].id}", headers=cs_headers)
    assert resp.status_code == 200
    assert resp.json()["shares"][0]["remain_times"] == 4


def test_ops_members_includes_cs_name(client, ops_headers):
    members = _seed_binding_data()
    resp = client.get("/api/ops/members?search=700", headers=ops_headers)
    assert resp.status_code == 200
    by_ext = {i["ext_member_id"]: i for i in resp.json()["items"]}
    assert by_ext[7001]["cs_name"] == "t_cs"
    assert by_ext[7002]["cs_name"] == "t_cs2"


def test_ops_member_detail(client, ops_headers):
    members = _seed_binding_data()
    resp = client.get(f"/api/ops/members/{members[7001].id}", headers=ops_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cs_name"] == "t_cs" and len(body["shares"]) == 1


def test_cs_cannot_access_ops_members(client, cs_headers):
    assert client.get("/api/ops/members", headers=cs_headers).status_code == 403
