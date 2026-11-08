"""鉴权：注册、登录、token 校验、全局密钥配置"""
from conftest import register


def test_register_login_and_me(client):
    u = register(client)
    r = client.post("/api/auth/login", json={"username": u["username"], "password": u["password"]})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["user"]["username"] == u["username"]
    assert data["user"]["has_api_key"] is False

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == u["username"]


def test_register_duplicate_username(client):
    u = register(client)
    r = client.post("/api/auth/register", json={"username": u["username"], "password": "another-pass"})
    assert r.status_code == 400
    assert r.json()["detail"] == "用户名已存在"


def test_register_validation(client):
    r = client.post("/api/auth/register", json={"username": "ab", "password": "123"})
    assert r.status_code == 422


def test_login_wrong_password(client):
    u = register(client)
    r = client.post("/api/auth/login", json={"username": u["username"], "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["detail"] == "用户名或密码错误"


def test_protected_endpoint_requires_token(client):
    r = client.get("/api/projects")
    assert r.status_code == 403
    assert r.json()["detail"] == "未认证"


def test_invalid_token_rejected(client):
    r = client.get("/api/projects", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_token_via_query_param(client, user):
    """EventSource / 下载链接不能带请求头，token 走查询参数"""
    r = client.get("/api/projects", params={"token": user["token"]})
    assert r.status_code == 200


def test_global_key_config(client, user):
    h = user["headers"]
    assert client.get("/api/auth/config", headers=h).json()["data"]["has_api_key"] is False
    r = client.put("/api/auth/config", json={"doubao_api_key": "k-123", "doubao_model": "glm-4.5-flash"}, headers=h)
    assert r.status_code == 200
    cfg = client.get("/api/auth/config", headers=h).json()["data"]
    assert cfg["has_api_key"] is True
    assert cfg["doubao_model"] == "glm-4.5-flash"
    # 密钥本身不回传
    assert "doubao_api_key" not in cfg
