#!/usr/bin/env python3
"""生成授权签名用的 Ed25519 密钥对。

私钥只写入 --out 指定的文件（权限 600），绝不打印；
默认拒绝写到 git 仓库目录内。屏幕上只输出 kid 和公钥。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dongai_license.crypto import generate_keypair, key_id_for  # noqa: E402


def in_git_repo(directory: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except FileNotFoundError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="私钥输出路径（必须在 git 仓库之外）")
    ap.add_argument("--kid", help="自定义 kid，默认取公钥哈希前 4 字节")
    args = ap.parse_args(argv)

    out = Path(args.out).expanduser().resolve()
    if out.exists():
        print("错误：目标文件已存在，拒绝覆盖", file=sys.stderr)
        return 2
    parent = out.parent
    if not parent.is_dir():
        print("错误：输出目录不存在", file=sys.stderr)
        return 2
    if in_git_repo(parent):
        print("错误：输出路径在 git 仓库内，私钥不能放进仓库", file=sys.stderr)
        return 2

    priv, pub = generate_keypair()
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(priv + "\n")
    os.chmod(str(out), 0o600)

    print(f"kid: {args.kid or key_id_for(pub)}")
    print(f"public_key: {pub}")
    print(f"私钥已写入 {out}（权限 600），请转存到授权服务器的密钥管理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
