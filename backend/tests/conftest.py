"""后端接口测试公共夹具

测试对一个真实运行的后端发 HTTP 请求（httpx），不 mock 路由层：
- 设置了 DONGAI_API_BASE（scripts/e2e.sh 会设置）时直接用它；
- 否则在本进程起一个 uvicorn（替身模式），需要 MONGODB_URL，库名必须是测试库。

安全约束：库名必须包含 e2e 或 test，绝不碰 dongai 主库。
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

import httpx
import pytest
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _assert_test_db(name: str):
    if not name or name == "dongai" or not any(k in name for k in ("e2e", "test")):
        raise RuntimeError(f"拒绝在非测试库上跑测试: MONGODB_DB_NAME={name!r}（库名需包含 e2e 或 test）")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def db_name() -> str:
    name = os.environ.get("MONGODB_DB_NAME", "dongai_e2e")
    _assert_test_db(name)
    return name


@pytest.fixture(scope="session")
def mongo(db_name):
    url = os.environ.get("MONGODB_URL")
    if not url:
        pytest.skip("未设置 MONGODB_URL；请用 scripts/e2e.sh 运行")
    client = MongoClient(url, serverSelectionTimeoutMS=8000)
    yield client[db_name]
    client.close()


@pytest.fixture(scope="session")
def api_base(mongo, db_name):
    base = os.environ.get("DONGAI_API_BASE")
    if base:
        yield base.rstrip("/")
        return
    # 自己起一个替身模式后端
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="dongai-pytest-"))
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "mongo_url")}
    env.update({
        "MONGODB_DB_NAME": db_name,
        "DONGAI_FAKE_PROVIDERS": "1",
        "STATIC_DIR": str(tmp / "static"),
        "JIANYING_DRAFT_DIR": str(tmp / "jianying"),
        "JIANYING_TEMPLATE_DIR": str(FIXTURES / "jianying_template"),
        "REDIS_URL": "redis://127.0.0.1:6/0",
        "JWT_SECRET": env.get("JWT_SECRET") or uuid.uuid4().hex,
    })
    (tmp / "jianying").mkdir(parents=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("后端没有在 30 秒内就绪")
        os.environ.setdefault("STATIC_DIR", str(tmp / "static"))
        os.environ.setdefault("JIANYING_DRAFT_DIR", str(tmp / "jianying"))
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def client(api_base):
    with httpx.Client(base_url=api_base, timeout=120, trust_env=False) as c:
        yield c


def register(client, prefix: str = "u") -> dict:
    """注册一个新用户，返回 {username, password, token, headers, id}"""
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    password = "e2e-pass-123"
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    token = data["token"]
    return {"username": username, "password": password, "token": token, "id": data["user"]["id"],
            "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def user(client):
    """未配置密钥的新用户"""
    return register(client)


@pytest.fixture
def keyed_user(client):
    """已配置全局密钥的新用户（替身模式下密钥不会真的发出去）"""
    u = register(client, "k")
    r = client.put("/api/auth/config", json={"doubao_api_key": "e2e-fake-key"}, headers=u["headers"])
    assert r.status_code == 200, r.text
    return u


@pytest.fixture
def project(client, keyed_user):
    r = client.post("/api/projects", json={"name": "暴雨演武场", "genre": "玄幻"}, headers=keyed_user["headers"])
    assert r.status_code == 200, r.text
    return {"id": r.json()["data"]["id"], "user": keyed_user}


def _seed_accounts(mongo, n: int = 3) -> list:
    today = str(date.today())
    ids = []
    for i in range(1, n + 1):
        acc_id = f"e2e_account_{i}"
        mongo.doubao_accounts.update_one({"id": acc_id}, {"$set": {
            "id": acc_id, "name": f"替身账号{i}", "profile_dir": "", "cookies": [],
            "enabled": True, "logged_in": True, "usage": {"date": today, "count": 0},
        }}, upsert=True)
        ids.append(acc_id)
    return ids


@pytest.fixture(scope="session", autouse=True)
def seed_accounts(mongo):
    """先放好替身视频账号，避免账号池首次运行时把仓库里的 doubao_accounts.json 导进测试库"""
    _seed_accounts(mongo)


@pytest.fixture
def video_accounts(mongo):
    """视频账号池：每个测试重置今日用量（每号每天限 2 条）"""
    return _seed_accounts(mongo)


@pytest.fixture(scope="session")
def static_dir() -> Path:
    path = os.environ.get("STATIC_DIR")
    if not path:
        pytest.skip("未设置 STATIC_DIR")
    return Path(path)
