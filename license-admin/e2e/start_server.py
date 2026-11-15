#!/usr/bin/env python3
"""仅用于 e2e：用内存仓库启动授权服务（端口 18100），并预建三个角色的管理员。

- 不提供给生产使用：内存仓库重启即丢失；额外挂了一个 /e2e/activate/{lid} 接口，用来把 pending 授权置为 active
  （真正的激活流程是 L-42 的客户端激活，这里还没有，管理端的「停用」只能对 active 授权操作）。
- 密码从环境变量 E2E_ADMIN_PASSWORD 读取（至少 12 位），不写死在仓库里。
- 签名私钥默认由 license/scripts/gen_keys.py 生成在系统临时目录（git 仓库之外），进程退出时删除；
  设置 E2E_SIGNING_KEY_FILE 可改用固定私钥（不会被删除），见 scripts/run_demo_license_server.sh。
- 监听地址固定 127.0.0.1，端口取 E2E_LICENSE_PORT（默认 18100）。
- 管理员用户名：e2e_super / e2e_ops / e2e_readonly。

    E2E_ADMIN_PASSWORD=... python3 e2e/start_server.py
"""
from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "license-server"))
sys.path.insert(0, str(ROOT / "license"))

PORT = int(os.environ.get("E2E_LICENSE_PORT", "18100"))


def main() -> int:
    password = os.environ.get("E2E_ADMIN_PASSWORD", "")
    if len(password) < 12:
        print("请通过环境变量 E2E_ADMIN_PASSWORD 提供至少 12 位的管理员密码", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="dongai-e2e-keys-"))
    try:
        fixed = os.environ.get("E2E_SIGNING_KEY_FILE", "").strip()
        if fixed:
            # 使用固定的测试私钥（演示/测试 dmg 用），文件由调用方保管，退出时不删除
            key_file = Path(fixed).expanduser()
            if not key_file.is_file():
                print(f"E2E_SIGNING_KEY_FILE 指向的文件不存在：{key_file}", file=sys.stderr)
                return 2
        else:
            key_file = tmp / "signing.key"
            subprocess.run([sys.executable, str(ROOT / "license" / "scripts" / "gen_keys.py"), "--out", str(key_file)],
                           check=True, stdout=subprocess.DEVNULL)
        os.environ.update({
            "LS_STORE": "memory",
            "LS_JWT_SECRET": secrets.token_urlsafe(48),
            "LS_SIGNING_PRIVATE_KEY_FILE": str(key_file),
            "LS_FEATURES": "video,image,e2e_feat",  # 验证管理端的功能点候选来自服务端 /meta
        })

        import uvicorn
        from app.config import load_settings
        from app.create_admin import create_admin_in_repo
        from app.main import create_app
        from app.repo.memory import make_memory_repos
        from app.services.audit import Actor

        settings = load_settings()
        repos = make_memory_repos()
        for name, role in (("e2e_super", "super"), ("e2e_ops", "ops"), ("e2e_readonly", "readonly")):
            asyncio.run(create_admin_in_repo(repos, name, password, role))

        app = create_app(settings, repos)

        @app.post("/e2e/activate/{lid}")
        async def _activate(lid: str):
            await app.state.ctx.licenses.mark_activated(lid, Actor(None, "e2e"))
            return {"ok": True}

        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
