"""假 mongod：只监听 --port 指定的端口，用来测试 MongodManager（不依赖真 mongod）。

环境变量 FAKE_MONGOD_MODE：
  ok（默认）  正常监听，收到 SIGTERM 退出码 0
  exit        启动后立刻退出码 3
  slow        等 FAKE_MONGOD_DELAY 秒后才开始监听
  ignore_term 忽略 SIGTERM（测强杀）
  crash_after 监听 FAKE_MONGOD_DELAY 秒后退出码 9（模拟崩溃）
"""
import os
import signal
import socket
import sys
import time

argv = sys.argv[1:]
port = int(argv[argv.index("--port") + 1])
mode = os.environ.get("FAKE_MONGOD_MODE", "ok")
delay = float(os.environ.get("FAKE_MONGOD_DELAY", "0"))
if mode == "exit":
    sys.exit(3)
if mode == "slow":
    time.sleep(delay)
if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port))
srv.listen(8)
srv.settimeout(0.1)
start = time.time()
while True:
    if mode == "crash_after" and time.time() - start > delay:
        sys.exit(9)
    try:
        c, _ = srv.accept()
        c.close()
    except socket.timeout:
        pass
