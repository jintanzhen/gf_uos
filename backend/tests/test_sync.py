# -*- coding: utf-8 -*-
"""M1 同步管线单测：FakeClient 模拟源系统分页接口，验证五类同步与双口径归属匹配。"""
import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.member import Member
from app.models.operator import CsMemberBinding, Operator
from app.models.order import ExtOrder
from app.models.share import ShareDetail
from app.models.system import SyncLog
from app.spider import sync as sync_mod
from app.spider.sync import sync_binding, sync_member, sync_order, sync_share, sync_staff


class FakeClient:
    """最小源系统模拟：table → 行列表；iter_page_rows 直接全量吐出。"""

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def iter_page_rows(self, table, *, page_size=5000, sort=None, order="desc",
                       wheres=None, stop_when=None, max_rows=None):
        for row in self.tables.get(table, []):
            if stop_when is not None and stop_when(row):
                return
            yield row

    def get_page(self, table, page=1, rows=20, sort=None, order="desc", wheres=None, **extra):
        data = self.tables.get(table, [])
        start = (page - 1) * rows
        return {"total": len(data), "rows": data[start:start + rows]}


def _fake_tables() -> dict[str, list[dict]]:
    return {
        "StaffInfo": [
            {"ID": "22", "StaffName": "瓜娃子", "Phone": "13380613693",
             "QRCodeURL": "https://img.example/q22", "ModifyDate": "2026-11-20 08:00:00",
             "MemberList": "101,102,13800138000,99999"},
            {"ID": "23", "StaffName": "小土豆", "Phone": "13380613694",
             "QRCodeURL": None, "ModifyDate": "2026-11-20 08:01:00",
             "MemberList": "103"},
        ],
        "memberinfo": [
            {"MemID": "101", "NickName": "菜友一", "RealName": "张一", "Mobile": "13800138000",
             "AnotherPhone": "", "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:00:00"},
            {"MemID": "101", "NickName": "菜友一", "RealName": "张一", "Mobile": "13800138000",
             "AnotherPhone": "", "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:00:00"},  # 跨页重复行（回归：排序不稳定）
            {"MemID": "102", "NickName": "菜友二", "RealName": "李二", "Mobile": "13800138001",
             "AnotherPhone": "", "CreateDate": "2024-01-02 00:00:00", "ModifyDate": "2026-11-20 09:01:00"},
            {"MemID": "103", "NickName": "菜友三", "RealName": "王三", "Mobile": "13800138002",
             "AnotherPhone": "", "CreateDate": "2024-01-03 00:00:00", "ModifyDate": "2026-11-20 09:02:00"},
        ],
        "OrderInfo": [
            {"ID": "order-fene-1", "MemID": "101", "OrderType": "FenE", "OrderStatus": "2",
             "SuiFenePeisongStatus": "配送中", "ModifyDate": "2026-11-20 10:00:00"},
            {"ID": "order-sandan-1", "MemID": "102", "OrderType": "SanDan", "OrderStatus": "2",
             "SuiFenePeisongStatus": "", "ModifyDate": "2026-11-20 10:01:00"},
        ],
        "OrderDetail": [
            {"ID": "detail-1", "OrderID": "order-fene-1", "MemID": "101", "GoodID": "501",
             "LoopShipCount": "12", "LoopShipedTimes": "8", "RemainShipTimes": "4",
             "LoopShipDescription": "每周配送一次", "StartShipDate": "2026-09-01",
             "EndShipDate": "2026-12-01", "ModifyDate": "2026-11-20 11:00:00"},
            {"ID": "detail-2", "OrderID": "order-sandan-1", "MemID": "102", "GoodID": "502",
             "LoopShipCount": "0", "LoopShipedTimes": "0", "RemainShipTimes": "0",
             "ModifyDate": "2026-11-20 11:01:00"},  # 散单 → 应跳过
            {"ID": "detail-3", "OrderID": "order-fene-1", "MemID": "99999", "GoodID": "501",
             "LoopShipCount": "10", "LoopShipedTimes": "1", "RemainShipTimes": "9",
             "ModifyDate": "2026-11-20 11:02:00"},  # 会员不存在 → 应跳过
        ],
        "CaipinInfo": [
            {"GoodJstSkuCode": "SKU-501", "FeneType": "shucai"},
        ],
        "jstGood": [
            {"ID": "501", "sku_id": "SKU-501", "GoodName": "有机蔬菜份额"},
        ],
    }


def test_full_pipeline(client, seeded_operators):
    fake = FakeClient(_fake_tables())

    r_staff = sync_staff(SessionLocal(), fake)
    assert r_staff["created"] == 2
    assert r_staff["local"] >= 2  # 会话内其他测试可能新增同步客服（人员管理等）

    db = SessionLocal()
    r_member = sync_member(db, fake)
    assert r_member["created"] == 3

    r_order = sync_order(db, fake)
    assert r_order["created"] == 2

    r_share = sync_share(db, fake)
    # detail-1 应入库；detail-2 散单跳过；detail-3 会员不存在跳过
    assert r_share["created"] == 1
    assert r_share["skipped_not_fene"] == 1
    assert r_share["skipped_no_member"] == 1

    r_binding = sync_binding(db, fake)
    # 瓜娃子: 101(memid) + 102(memid) + 13800138000(mobile→101)；小土豆: 103(memid)；99999 未匹配
    assert r_binding["matched_by_memid"] == 3
    assert r_binding["matched_by_mobile"] == 1
    assert r_binding["unmatched_count"] == 1

    # ---- 断言落库结果 ----
    share = db.scalar(select(ShareDetail).where(ShareDetail.ext_detail_id == "detail-1"))
    assert share is not None
    assert share.remain_times == 4
    assert share.order_status == 2          # 从 ext_order 回填
    assert share.share_type == "shucai"     # GoodID → SKU → FeneType 链路
    assert share.good_name == "有机蔬菜份额"
    mem101 = db.scalar(select(Member).where(Member.ext_member_id == 101))
    assert share.member_id == mem101.id

    # R1：member 101 只有一条 is_current=1 绑定，指向瓜娃子
    cs = db.scalar(select(Operator).where(Operator.ext_cs_id == 22))
    bindings = db.scalars(
        select(CsMemberBinding).where(
            CsMemberBinding.member_id == mem101.id, CsMemberBinding.is_current.is_(True)
        )
    ).all()
    assert len(bindings) == 1 and bindings[0].cs_id == cs.id

    # 游标已前移
    from app.models.system import SpiderCursor
    cur = db.get(SpiderCursor, "memberinfo")
    assert cur is not None and cur.last_sync_time is not None
    db.close()


def test_sync_idempotent(client, seeded_operators):
    """F1-07：重跑不产生重复数据。"""
    fake = FakeClient(_fake_tables())
    db = SessionLocal()
    sync_staff(db, fake)
    sync_member(db, fake)
    sync_order(db, fake)
    sync_share(db, fake)
    sync_binding(db, fake)

    assert db.query(Member).filter(Member.ext_member_id.in_([101, 102, 103])).count() == 3
    assert db.query(ExtOrder).filter(ExtOrder.ext_order_id.in_(
        ["order-fene-1", "order-sandan-1"])).count() == 2
    assert db.query(ShareDetail).filter(ShareDetail.ext_detail_id == "detail-1").count() == 1
    assert db.query(Operator).filter(Operator.ext_cs_id.is_not(None)).count() >= 2
    db.close()


def test_sync_log_written(client, seeded_operators):
    """F1-08：每类同步写 sync_log（取最新一条校验）。"""
    fake = FakeClient(_fake_tables())
    db = SessionLocal()
    sync_member(db, fake)
    log = db.scalar(select(SyncLog).where(SyncLog.sync_type == "member").order_by(SyncLog.id.desc()))
    assert log is not None
    assert log.status == "ok"
    assert json.loads(log.detail_json)["local"] >= 3  # 共享库可能含其他测试的数据
    db.close()

def test_binding_three_tier_priority(client, seeded_operators):
    """三口径优先级：负责员工姓名 > MemberList MemID > 手机号；唯一归属（R1）。"""
    tables = {
        "StaffInfo": [
            {"ID": "22", "StaffName": "瓜娃子", "Phone": "13380613693", "QRCodeURL": None,
             "ModifyDate": "2026-11-20 08:00:00", "MemberList": "9401,13800138003"},
            {"ID": "23", "StaffName": "小土豆", "Phone": "13380613694", "QRCodeURL": None,
             "ModifyDate": "2026-11-20 08:01:00", "MemberList": "9401,9402"},
        ],
        "memberinfo": [
            # 9401：负责员工=瓜娃子，同时出现在两个客服的 MemberList → 口径 a 胜出
            {"MemID": "9401", "NickName": "三口径一", "Mobile": "13800138001", "Staff": "瓜娃子",
             "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:00:00"},
            # 9402：无负责员工，仅在 小土豆 MemberList → 口径 b
            {"MemID": "9402", "NickName": "三口径二", "Mobile": "13800138002",
             "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:01:00"},
            # 9403：无负责员工、不在 MemberList，手机号在 瓜娃子 MemberList → 口径 c
            {"MemID": "9403", "NickName": "三口径三", "Mobile": "13800138003",
             "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:02:00"},
            # 9404：负责员工=无患子（无此客服）→ 不绑定
            {"MemID": "9404", "NickName": "三口径四", "Mobile": "13800138004", "Staff": "无患子",
             "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:03:00"},
            # 9405：负责员工同为瓜娃子（同名多会员，防一对一映射回归）
            {"MemID": "9405", "NickName": "三口径五", "Mobile": "13800138005", "Staff": "瓜娃子",
             "CreateDate": "2024-01-01 00:00:00", "ModifyDate": "2026-11-20 09:04:00"},
        ],
    }
    fake = FakeClient(tables)
    db = SessionLocal()
    sync_staff(SessionLocal(), fake)
    sync_member(db, fake)
    r = sync_binding(db, fake)

    assert r["matched_by_staff"] == 2  # 9401 + 9405（同名负责员工都要绑定）
    assert r["staff_unmatched_names"] == ["无患子"]
    assert r["matched_by_memid"] == 3   # 9401 被两个客服 MemberList 各命中一次 + 9402（口径命中次数）
    assert r["matched_by_mobile"] == 1

    from app.models.operator import CsMemberBinding, Operator
    m = {mid: db.scalar(select(Member).where(Member.ext_member_id == mid))
         for mid in (9401, 9402, 9403, 9404, 9405)}
    ops = {o.name: o for o in db.query(Operator).filter(Operator.ext_cs_id.is_not(None)).all()}

    b1 = db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m[9401].id).first()
    assert b1 is not None and b1.is_current
    assert b1.source == "MemberInfo.Staff" and b1.cs_id == ops["瓜娃子"].id

    b2 = db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m[9402].id).first()
    assert b2 is not None and b2.source == "StaffInfo" and b2.cs_id == ops["小土豆"].id

    b3 = db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m[9403].id).first()
    assert b3 is not None and b3.source == "Mobile" and b3.cs_id == ops["瓜娃子"].id

    b4 = db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m[9404].id).first()
    assert b4 is None  # 负责员工无对应客服 → 不绑定，走公共池

    b5 = db.query(CsMemberBinding).filter(CsMemberBinding.member_id == m[9405].id).first()
    assert b5 is not None and b5.source == "MemberInfo.Staff" and b5.cs_id == ops["瓜娃子"].id
    db.close()
