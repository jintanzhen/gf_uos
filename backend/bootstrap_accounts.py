# -*- coding: utf-8 -*-
"""为源系统同步的客服账号设置统一初始密码（方案 A）。

登录名 = StaffName（如 瓜娃子），初始密码 = cs123。
幂等：仅处理 password_hash='!'（不可登录占位）的账号，已设密的账号不动，
后续改密走超管「人员管理」重置密码（POST /api/admin/operators/{id}/reset-password）。
可重跑。
"""
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.operator import Operator

DEFAULT_PASSWORD = "cs123"
PLACEHOLDER = "!"


def main() -> None:
    db = SessionLocal()
    try:
        targets = (
            db.query(Operator)
            .filter(Operator.ext_cs_id.is_not(None), Operator.password_hash == PLACEHOLDER)
            .order_by(Operator.ext_cs_id)
            .all()
        )
        if not targets:
            print("无需处理：同步客服账号均已设置密码（或不存在同步客服）")
            return
        for op in targets:
            op.password_hash = hash_password(DEFAULT_PASSWORD)
            print(f"已设置账号: {op.name} (operator.id={op.id}, ext_cs_id={op.ext_cs_id})")
        db.commit()
        print(f"完成：{len(targets)} 个客服账号初始密码已设置为 {DEFAULT_PASSWORD}，请提醒客服尽快修改")
    finally:
        db.close()


if __name__ == "__main__":
    main()
