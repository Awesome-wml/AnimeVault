import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "license"))  # 共享库 dongai_license

from fastapi.testclient import TestClient  # noqa: E402

from app.config import DbSettings, Settings, _derive_public  # noqa: E402
from app.create_admin import create_admin_in_repo  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repo.memory import make_memory_repos  # noqa: E402
from dongai_license import crypto  # noqa: E402
from dongai_license.machine_code import format_machine_code  # noqa: E402

PW = "correct horse battery"


def comps(n=3, seed=1):
    return [f"{seed:02x}{i:02x}" + "ab" * 6 for i in range(n)]


def mcode(n=3, seed=1):
    return format_machine_code(comps(n, seed))


@pytest.fixture
def keys():
    priv, pub = crypto.generate_keypair()
    return priv, pub, crypto.key_id_for(pub)


@pytest.fixture
def settings(keys):
    priv, pub, kid = keys
    return Settings(db=DbSettings(store="memory"), jwt_secret="t" * 8 + "x9K2mQ7vLp4Zr1Wn6Yb3Hd5Gs8Jc0Fa",
                    signing_private_key=priv, signing_public_key=pub, signing_kid=kid)


@pytest.fixture
def repos():
    return make_memory_repos()


@pytest.fixture
def client(settings, repos):
    with TestClient(create_app(settings, repos)) as c:
        yield c


def make_admin(repos, username, role="super", password=PW):
    return asyncio.run(create_admin_in_repo(repos, username, password, role))


def login(client, username, password=PW):
    r = client.post("/admin/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def root(client, repos):
    make_admin(repos, "root", "super")
    return login(client, "root")


@pytest.fixture
def ops(client, repos, root):
    make_admin(repos, "oper", "ops")
    return login(client, "oper")


@pytest.fixture
def ro(client, repos, root):
    make_admin(repos, "viewer", "readonly")
    return login(client, "viewer")


def issue_body(**kw):
    b = {"machine_code": mcode(), "plan": "pro", "features": ["video"],
         "expires_at": int(time.time()) + 86400 * 30, "email": "u@example.com"}
    b.update(kw)
    return b
