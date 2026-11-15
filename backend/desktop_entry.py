"""桌面版后端启动入口：由 Electron 外壳拉起。

选空闲端口、生成一次性令牌，只绑定 127.0.0.1，启动后在 stdout 打印一行
{"event":"ready","port":端口,"token":"令牌"} 供外壳读取。
"""
import json
import os
import secrets
import socket
import sys
import threading
import time

os.environ.setdefault("DONGAI_DESKTOP", "1")


def pick_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    import uvicorn

    port = pick_free_port()
    token = secrets.token_urlsafe(32)
    os.environ["DONGAI_LOCAL_TOKEN"] = token

    import main as app_module  # 在令牌设置之后再导入应用

    config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port, loop="asyncio",
                            log_level="info", access_log=False)
    server = uvicorn.Server(config)

    def announce():
        # server.started 在 lifespan 启动完成（含 Mongo 连接）后置位
        while not server.started and thread.is_alive():
            time.sleep(0.1)
        if server.started:
            print(json.dumps({"event": "ready", "port": port, "token": token}), flush=True)

    thread = threading.current_thread()
    threading.Thread(target=announce, daemon=True).start()
    server.run()
    if not server.started:
        sys.exit(1)


if __name__ == "__main__":
    main()
