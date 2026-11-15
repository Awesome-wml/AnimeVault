"""桌面模式本地令牌校验（纯 ASGI 中间件，不缓冲 SSE 流）。

环境变量 DONGAI_LOCAL_TOKEN 存在时，所有 /api/* 请求必须带请求头
X-DongAI-Local-Token 且值匹配，否则 401。/health、/static/*、/docs 等非 /api 路径放行；
OPTIONS 预检放行。环境变量不存在时中间件不生效。
"""
import hmac
import json
import os

HEADER = b"x-dongai-local-token"
TOKEN_ENV = "DONGAI_LOCAL_TOKEN"


class LocalTokenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        expected = os.environ.get(TOKEN_ENV)
        if scope["type"] != "http" or not expected:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if scope.get("method") == "OPTIONS" or not (path == "/api" or path.startswith("/api/")):
            return await self.app(scope, receive, send)
        got = b""
        for k, v in scope.get("headers", []):
            if k == HEADER:
                got = v
                break
        if hmac.compare_digest(got, expected.encode("utf-8")):
            return await self.app(scope, receive, send)
        body = json.dumps({"detail": "本地令牌无效"}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
