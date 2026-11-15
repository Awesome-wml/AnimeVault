"""命令行创建管理员（首个管理员只能这样创建）。

    PYTHONPATH=../license python -m app.create_admin --username alice [--role super]

密码交互输入，不接受命令行传入；没有任何默认账号。
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from .config import ConfigError, load_db_settings
from .db import make_repos
from .errors import ApiError
from .services.admins import AdminService
from .services.audit import Actor, AuditService


async def create_admin_in_repo(repos, username: str, password: str, role: str = "super") -> dict:
    audit = AuditService(repos.audit)
    svc = AdminService(repos, audit, "unused", 0)
    return await svc.create(Actor(None, "cli"), username, password, role)


async def _run(username: str, password: str, role: str) -> int:
    try:
        db = load_db_settings()
    except ConfigError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        return 2
    if db.store != "mongo":
        print("内存仓库重启即丢失，命令行创建管理员只适用于 LS_STORE=mongo", file=sys.stderr)
        return 2
    repos = make_repos(db)
    try:
        await repos.ensure_ready()
        a = await create_admin_in_repo(repos, username, password, role)
    except ApiError as e:
        print(f"创建失败：{e.message}", file=sys.stderr)
        return 1
    finally:
        await repos.close()
    print(f"已创建管理员 {a['username']}（{a['role']}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--username", required=True)
    ap.add_argument("--role", default="super", choices=["super", "ops", "readonly"])
    args = ap.parse_args(argv)
    pw = getpass.getpass("密码（至少 12 位）：")
    if pw != getpass.getpass("再输入一次："):
        print("两次密码不一致", file=sys.stderr)
        return 1
    return asyncio.run(_run(args.username, pw, args.role))


if __name__ == "__main__":
    sys.exit(main())
