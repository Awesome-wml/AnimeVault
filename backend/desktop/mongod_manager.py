"""桌面版随包 mongod 的进程管理（L-04 原型）

职责：选空闲端口、拉起 mongod、等就绪、优雅停止、崩溃后自动重启、处理上次异常退出留下的锁文件。
只绑定 127.0.0.1；不依赖 mongod 之外的任何服务。
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Sequence, Union

logger = logging.getLogger("dongai.mongod")

HOST = "127.0.0.1"


class MongodError(RuntimeError):
    """mongod 启动 / 运行失败"""


def find_free_port(host: str = HOST) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class MongodManager:
    def __init__(
        self,
        binary_path: Union[str, Path, Sequence[Union[str, Path]]],
        data_dir: Union[str, Path],
        port: Optional[int] = None,
        *,
        log_path: Union[str, Path, None] = None,
        ready_timeout: float = 30.0,
        stop_timeout: float = 10.0,
        max_restarts: int = 3,
        cache_size_gb: Optional[float] = 0.25,
        ping: bool = True,
        extra_args: Sequence[str] = (),
    ):
        # binary_path 可以是单个路径，也可以是命令前缀列表（测试里用 [python, fake.py]）
        if isinstance(binary_path, (str, Path)):
            self._cmd_prefix = [str(binary_path)]
        else:
            self._cmd_prefix = [str(p) for p in binary_path]
        self.data_dir = Path(data_dir)
        self._fixed_port = port
        self.port: Optional[int] = port
        self.log_path = Path(log_path) if log_path else self.data_dir.parent / "mongod.log"
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.max_restarts = max_restarts
        self.cache_size_gb = cache_size_gb
        self.ping = ping
        self.extra_args = list(extra_args)
        self.restart_count = 0
        self.recovered_unclean = False  # 本次启动前发现上次异常退出（mongod 会靠 journal 自行恢复）
        self._proc: Optional[subprocess.Popen] = None
        self._log_fh = None
        self._lock = threading.RLock()

    # ---- 状态 ----
    @property
    def is_running(self) -> bool:
        p = self._proc
        return p is not None and p.poll() is None

    @property
    def url(self) -> str:
        if self.port is None:
            raise MongodError("mongod 尚未启动，没有端口")
        return f"mongodb://{HOST}:{self.port}/"

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self.is_running else None

    # ---- 锁文件 ----
    def _check_lock_file(self) -> None:
        """数据目录里 mongod.lock 非空 = 上次没正常退出，或者另一个 mongod 正占用。

        - 里面的 pid 还活着（且不是我们自己的子进程）：别人在用，直接报错，避免两个 mongod 写同一目录；
        - pid 已不存在：异常退出残留。不删文件，mongod 启动时会按 journal 恢复；只记一个标记和日志。
        """
        lock = self.data_dir / "mongod.lock"
        self.recovered_unclean = False
        try:
            text = lock.read_text().strip()
        except (FileNotFoundError, OSError):
            return
        if not text:
            return
        try:
            pid = int(text)
        except ValueError:
            pid = 0
        if pid and _pid_alive(pid) and not (self._proc and self._proc.pid == pid):
            raise MongodError(f"数据目录 {self.data_dir} 正被进程 {pid} 占用（mongod.lock），请先关闭它")
        self.recovered_unclean = True
        logger.warning("检测到上次异常退出（mongod.lock 残留 pid=%s），启动后由 mongod 通过 journal 恢复", text)

    # ---- 启动 ----
    def _build_cmd(self) -> list:
        cmd = self._cmd_prefix + [
            "--dbpath", str(self.data_dir),
            "--bind_ip", HOST,
            "--port", str(self.port),
            "--logpath", str(self.log_path),
            "--logappend",
        ]
        if self.cache_size_gb:
            cmd += ["--wiredTigerCacheSizeGB", str(self.cache_size_gb)]
        return cmd + self.extra_args

    def _port_ready(self) -> bool:
        try:
            with socket.create_connection((HOST, self.port), timeout=0.3):
                pass
        except OSError:
            return False
        if not self.ping:
            return True
        try:
            from pymongo import MongoClient
            c = MongoClient(self.url, serverSelectionTimeoutMS=500, connectTimeoutMS=500)
            try:
                c.admin.command("ping")
            finally:
                c.close()
            return True
        except Exception:
            return False

    def start(self) -> str:
        """拉起 mongod 并等到可连接，返回连接串。已在运行则直接返回。"""
        with self._lock:
            if self.is_running:
                return self.url
            self.restart_count = 0
            return self._spawn()

    def _spawn(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._check_lock_file()
        if self.port is None or (self._fixed_port is None and not self._port_free(self.port)):
            self.port = find_free_port()
        elif self._fixed_port is not None and not self._port_free(self.port):
            raise MongodError(f"端口 {self.port} 已被占用")
        self._close_log()
        self._log_fh = open(self.log_path, "ab")
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(
                self._build_cmd(), stdout=self._log_fh, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, **kwargs)
        except OSError as e:
            self._close_log()
            raise MongodError(f"无法启动 mongod（{self._cmd_prefix[0]}）：{e}") from e
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            rc = self._proc.poll()
            if rc is not None:
                self._close_log()
                raise MongodError(f"mongod 启动后退出，返回码 {rc}，日志：{self.log_path}")
            if self._port_ready():
                logger.info("mongod 就绪 pid=%s port=%s", self._proc.pid, self.port)
                return self.url
            time.sleep(0.05)
        self._kill()
        raise MongodError(f"mongod 在 {self.ready_timeout:g} 秒内未就绪，日志：{self.log_path}")

    @staticmethod
    def _port_free(port: int) -> bool:
        with socket.socket() as s:
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # 忽略 TIME_WAIT，崩溃重启才能沿用原端口
            try:
                s.bind((HOST, port))
                return True
            except OSError:
                return False

    # ---- 停止 ----
    def stop(self) -> None:
        """优雅停止：POSIX 发 SIGTERM，Windows 先发 shutdown 命令；超时再强杀。"""
        with self._lock:
            p = self._proc
            if p is None:
                return
            if p.poll() is None:
                self._graceful(p)
                try:
                    p.wait(timeout=self.stop_timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("mongod 在 %ss 内未退出，强制结束", self.stop_timeout)
                    self._kill()
            self._proc = None
            self._close_log()

    def _graceful(self, p: subprocess.Popen) -> None:
        if sys.platform == "win32":
            if self.ping and self.port:
                try:
                    from pymongo import MongoClient
                    c = MongoClient(self.url, serverSelectionTimeoutMS=1000)
                    try:
                        c.admin.command("shutdown", 1, force=True)
                    except Exception:
                        pass  # shutdown 会断开连接，必然抛错
                    finally:
                        c.close()
                    return
                except Exception:
                    pass
            p.terminate()
        else:
            p.terminate()  # SIGTERM

    def _kill(self) -> None:
        p = self._proc
        if p is not None and p.poll() is None:
            p.kill()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def _close_log(self) -> None:
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None

    # ---- 崩溃自愈 ----
    def ensure_running(self) -> str:
        """进程在跑就直接返回连接串；挂了就重启（沿用原端口），最多 max_restarts 次。"""
        with self._lock:
            if self.is_running:
                return self.url
            if self._proc is None and self.port is None:
                return self.start()
            if self.restart_count >= self.max_restarts:
                raise MongodError(f"mongod 已崩溃并重启 {self.restart_count} 次，放弃重启，日志：{self.log_path}")
            self.restart_count += 1
            logger.warning("mongod 已退出，第 %s 次重启", self.restart_count)
            self._proc = None
            return self._spawn()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
