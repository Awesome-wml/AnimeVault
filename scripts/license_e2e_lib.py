"""授权端到端公用部件（L-29）：进程内授权服务（内存/Mongo）、admin API 客户端、临时 mongod、检查记录。

被 scripts/license_e2e.py 和 desktop/smoke_test.py 共用。需要 license-server 的依赖（fastapi、uvicorn、motor），
所以必须用装了依赖的 Python 运行（~/.local/dongai-venv/bin/python）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "license-server"))
sys.path.insert(0, str(ROOT / "license"))

ADMIN_USER = "e2e-root"
ADMIN_PASSWORD = "e2e-correct-horse-battery"
JWT_SECRET = "e2eX9K2mQ7vLp4Zr1Wn6Yb3Hd5Gs8Jc0FaT"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_json(method: str, url: str, body=None, headers=None, timeout=30):
    """返回 (状态码, 解析后的 JSON 或文本)。不走系统代理。"""
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw.decode("utf-8", "replace")


def find_mongod() -> str | None:
    env = os.environ.get("DONGAI_MONGOD_BIN")
    if env and Path(env).exists():
        return env
    for p in sorted((Path.home() / ".local" / "dongai-spike").glob("bin-*/*/bin/mongod")):
        return str(p)
    return shutil.which("mongod")


class TempMongod:
    """临时 mongod：数据目录在临时目录，只绑 127.0.0.1，结束即删。"""

    def __init__(self, binary: str, workdir: Path):
        self.port = free_port()
        self.dbpath = workdir / "mongo-db"
        self.dbpath.mkdir(parents=True)
        self.proc = subprocess.Popen(
            [binary, "--dbpath", str(self.dbpath), "--bind_ip", "127.0.0.1", "--port", str(self.port),
             "--nounixsocket", "--logpath", str(workdir / "mongod.log")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.url = f"mongodb://127.0.0.1:{self.port}"
        end = time.time() + 40
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.5).close()
                return
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("临时 mongod 启动失败，见 " + str(workdir / "mongod.log"))
                time.sleep(0.2)
        raise RuntimeError("临时 mongod 40 秒内没有就绪")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class LicenseServer:
    """进程内起一个真实的 license-server（uvicorn 线程）。store = memory | mongo。"""

    def __init__(self, priv_key_file: Path, store: str = "memory", mongo_url: str | None = None,
                 port: int = 0, mongo_db: str = "dongai_license_e2e"):
        from app.config import load_settings
        from app.create_admin import create_admin_in_repo
        from app.db import make_repos
        from app.main import create_app

        env = {"LS_STORE": store, "LS_JWT_SECRET": JWT_SECRET, "LS_SIGNING_PRIVATE_KEY_FILE": str(priv_key_file),
               "LS_EXPIRE_INTERVAL_SECONDS": "0", "LS_MONGO_DB": mongo_db}
        if mongo_url:
            env["LS_MONGO_URL"] = mongo_url
        self.settings = load_settings(env)
        self.store = store
        repos = None
        if store == "memory":
            from app.repo.memory import make_memory_repos
            repos = make_memory_repos()
            asyncio.run(create_admin_in_repo(repos, ADMIN_USER, ADMIN_PASSWORD, "super"))
        else:  # Mongo 客户端绑定事件循环：管理员用独立连接在独立循环里建，服务自己的连接在 uvicorn 的循环里建
            async def _mk():
                r = make_repos(self.settings.db)
                try:
                    await r.ensure_ready()
                    await create_admin_in_repo(r, ADMIN_USER, ADMIN_PASSWORD, "super")
                finally:
                    await r.close()
            asyncio.run(_mk())
        import uvicorn
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        cfg = uvicorn.Config(create_app(self.settings, repos), host="127.0.0.1", port=self.port,
                             log_level="warning", access_log=False)
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        end = time.time() + 30
        while time.time() < end and not self._server.started:
            time.sleep(0.1)
        if not self._server.started:
            raise RuntimeError("license-server 没有启动成功")
        self.kid, self.public_key = self.settings.signing_kid, self.settings.signing_public_key
        self._token = None

    def stop(self):
        self._server.should_exit = True
        self._thread.join(15)

    # ---- admin API
    def admin(self, method: str, path: str, body=None):
        if self._token is None:
            code, d = http_json("POST", self.url + "/admin/api/auth/login",
                                {"username": ADMIN_USER, "password": ADMIN_PASSWORD})
            assert code == 200, d
            self._token = d["token"]
        return http_json(method, self.url + "/admin/api" + path, body,
                         {"Authorization": "Bearer " + self._token})

    def issue(self, machine_code: str, days: int = 30, plan: str = "pro", features=("video",)):
        code, d = self.admin("POST", "/licenses", {
            "machine_code": machine_code, "plan": plan, "features": list(features),
            "expires_at": int(time.time()) + 86400 * days, "email": "e2e@example.com", "note": "L-29 e2e"})
        assert code == 201, (code, d)
        return d["license"]


class Checker:
    """记录并打印检查结果。"""

    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""), flush=True)
        return bool(ok)

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


def new_tmp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))
