# -*- coding: utf-8 -*-
"""运维 CLI（与 README 常用命令速查对应）：

    python -m app.cli create-admin --name admin [--password xxx]
    python -m app.cli sync --type member     # M1 实现
    python -m app.cli scan --rule-id 1       # M2 实现

用法（backend 目录，依赖由 uv 管理：uv sync 后）：
    uv run python -m app.cli ...
"""
import argparse
import getpass
import json
import sys

from .core.db import SessionLocal, ensure_sqlite_dir
from .core.security import hash_password
from .models.operator import Operator


def cmd_create_admin(args: argparse.Namespace) -> int:
    ensure_sqlite_dir()
    name = args.name
    password = args.password or getpass.getpass(f"为 [{name}] 设置密码: ")
    if not password:
        print("密码不能为空", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        exists = db.query(Operator).filter(Operator.name == name).first()
        if exists:
            print(f"账号 [{name}] 已存在（id={exists.id}，role={exists.role}）", file=sys.stderr)
            return 1
        operator = Operator(
            name=name,
            role=args.role,
            status="active",
            password_hash=hash_password(password),
        )
        db.add(operator)
        db.commit()
        print(f"已创建 {args.role} 账号: {name} (id={operator.id})")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from .spider import sync as sync_mod

    try:
        results = sync_mod.run_sync(args.type)
    except sync_mod.SyncRunning as exc:
        print(f"跳过：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(results, ensure_ascii=False, indent=1))
    failed = [k for k, v in results.items() if isinstance(v, dict) and v.get("status") == "failed"]
    if failed:
        print(f"失败步骤: {failed}（详见 sync_log，BR-08 不阻断）", file=sys.stderr)
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    target = args.rule_id if args.rule_id is not None else "全部规则"
    print(f"[占位] scan --rule-id {target}: 规则引擎将在 M2 实现（见 architecture.md §9）")
    return 0


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    parser = argparse.ArgumentParser(prog="app.cli", description="Green-OS 运维 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="创建超管账号")
    p_admin.add_argument("--name", required=True)
    p_admin.add_argument("--password", default="", help="不传则交互式输入")
    p_admin.add_argument("--role", default="admin", choices=["admin", "ops", "cs"], help="默认 admin")
    p_admin.set_defaults(func=cmd_create_admin)

    p_sync = sub.add_parser("sync", help="手动触发源系统同步")
    p_sync.add_argument("--type", default="all", choices=["all", "staff", "member", "order", "share", "binding"])
    p_sync.set_defaults(func=cmd_sync)

    p_scan = sub.add_parser("scan", help="手动重跑规则扫描（M2）")
    p_scan.add_argument("--rule-id", type=int, default=None)
    p_scan.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
