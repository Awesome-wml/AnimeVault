#!/usr/bin/env python3
"""打包产物冒烟测试（L-05），只用标准库，POSIX 版（Windows 需另写，见 README）。

用法：
    python desktop/smoke_test.py [--exe desktop/dist/dongai-backend/dongai-backend] [--mongod /path/to/mongod]

使用临时数据目录（用完删除）、DONGAI_DESKTOP=1、DONGAI_FAKE_PROVIDERS=1，依次验证：
  1 /health 200；2 不带令牌访问 /api/projects 为 401；3 注册/登录/建项目/列项目 + 替身 LLM 与替身出图；
  4 SIGTERM 后 mongod 也消失；5 kill -9 后端后再次启动能清理遗留 mongod、数据仍在；6 SIGINT 同样清理；
  7 --selfcheck（Playwright 驱动）。同时记录包体积、冷启动耗时、内存占用。
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = ROOT / "desktop" / "dist" / "dongai-backend" / "dongai-backend"
SPIKE_GLOB = Path.home() / ".local" / "dongai-spike"

results = []
metrics = {}


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    return ok


def find_mongod():
    env = os.environ.get("DONGAI_MONGOD_BIN")
    if env and Path(env).exists():
        return Path(env)
    for p in sorted(SPIKE_GLOB.glob("bin-*/*/bin/mongod")):
        return p
    return None


def pgrep(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if int(x) != os.getpid()]


def rss_mb(pid):
    r = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    try:
        return int(r.stdout.strip()) / 1024
    except ValueError:
        return 0.0


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def wait_dead(pid, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


class Backend:
    def __init__(self, exe, data_dir, mongod, extra_env=None):
        env = {k: v for k, v in os.environ.items() if k not in ("MONGODB_URL", "DONGAI_LOCAL_TOKEN")}
        env.update({"DONGAI_DATA_DIR": str(data_dir), "DONGAI_DESKTOP": "1", "DONGAI_FAKE_PROVIDERS": "1"})
        if mongod:
            env["DONGAI_MONGOD_BIN"] = str(mongod)
        env.update(extra_env or {})
        self.lines = []
        self.ready = None
        self.t0 = time.time()
        self.proc = subprocess.Popen([str(exe)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, start_new_session=True)
        self._ev = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())
            if self.ready is None and line.startswith("{"):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("event") == "ready":
                    self.ready = d
                    self.startup_s = time.time() - self.t0
                    self._ev.set()
        self._ev.set()

    def wait_ready(self, timeout=90):
        self._ev.wait(timeout)
        return self.ready

    @property
    def base(self):
        return f"http://127.0.0.1:{self.ready['port']}"

    def req(self, method, path, body=None, token=True, bearer=None, raw=False):
        headers = {}
        if token:
            headers["X-DongAI-Local-Token"] = self.ready["token"]
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                payload = resp.read()
                code = resp.status
        except urllib.error.HTTPError as e:
            payload, code = e.read(), e.code
        if raw:
            return code, payload
        try:
            return code, json.loads(payload)
        except ValueError:
            return code, payload.decode("utf-8", "replace")

    def children_rss(self):
        r = subprocess.run(["pgrep", "-P", str(self.proc.pid)], capture_output=True, text=True)
        return {int(p): rss_mb(int(p)) for p in r.stdout.split()}


def dir_size_h(path):
    r = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
    return r.stdout.split()[0]


def mongod_pids(data_dir):
    return pgrep(str(Path(data_dir) / "mongo"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(DEFAULT_EXE))
    ap.add_argument("--mongod", default="")
    args = ap.parse_args()
    exe = Path(args.exe)
    if not exe.exists():
        sys.exit(f"找不到可执行文件 {exe}，先运行 desktop/build_backend.py")
    mongod = Path(args.mongod) if args.mongod else find_mongod()
    bundled = exe.parent / "bin" / "mongod"
    if not mongod and not bundled.exists():
        print("没有可用的 mongod：只能做无 mongod 的验证（自检）")
    metrics["包体积（du -sh）"] = dir_size_h(exe.parent)
    tmp = Path(tempfile.mkdtemp(prefix="dongai-smoke-", dir=str(Path.home() / ".local" / "dongai-build")
                                if (Path.home() / ".local" / "dongai-build").exists() else None))
    data = tmp / "data"
    live = []
    try:
        # ---- 自检（不依赖 mongod）
        sc = subprocess.run([str(exe), "--selfcheck"], capture_output=True, text=True, timeout=180,
                            env={**os.environ, "DONGAI_DATA_DIR": str(data), "DONGAI_DESKTOP": "1"})
        try:
            info = json.loads(sc.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            info = {"raw": sc.stdout[-500:], "err": sc.stderr[-500:]}
        check("7 --selfcheck（Playwright 驱动）", sc.returncode == 0 and info.get("ok"), json.dumps(info, ensure_ascii=False))

        if not mongod and not bundled.exists():
            return
        # ---- 冷启动
        b = Backend(exe, data, mongod)
        live.append(b)
        ok = b.wait_ready()
        if not check("启动并打印 ready 行", ok, f"{ok and {'port': ok['port']}}"):
            print("\n".join(b.lines[-40:]))
            return
        metrics["冷启动到 ready（秒）"] = f"{b.startup_s:.1f}"
        mp = mongod_pids(data)
        check("随包 mongod 已拉起", len(mp) == 1, f"pid={mp}")
        pidfile = data / "mongod.pid"
        check("mongod.pid 已写入", pidfile.exists() and pidfile.read_text().strip() == str(mp[0] if mp else 0))

        # 1
        code, body = b.req("GET", "/health", token=False)
        check("1 /health 200", code == 200 and body.get("mongodb") == "connected", str(body))
        # 2
        code, _ = b.req("GET", "/api/projects", token=False)
        check("2 不带令牌访问 /api/projects 为 401", code == 401, f"got {code}")
        code, _ = b.req("GET", "/api/projects", token=False)
        # 3
        user = f"smoke_{uuid.uuid4().hex[:8]}"
        pwd = "smoke-pass-123"
        code, body = b.req("POST", "/api/auth/register", {"username": user, "password": pwd})
        check("3a 注册", code == 200, f"{code}")
        code, body = b.req("POST", "/api/auth/login", {"username": user, "password": pwd})
        jwt = body["data"]["token"] if code == 200 else None
        check("3b 登录", code == 200 and jwt, f"{code}")
        code, body = b.req("PUT", "/api/auth/config", {"doubao_api_key": "fake-key"}, bearer=jwt)
        code, body = b.req("POST", "/api/projects", {"name": "冒烟项目", "genre": "玄幻"}, bearer=jwt)
        pid = body["data"]["id"] if code == 200 else None
        check("3c 创建项目", code == 200 and pid, f"{code}")
        code, body = b.req("GET", "/api/projects", bearer=jwt)
        check("3d 列项目", code == 200 and [p["name"] for p in body] == ["冒烟项目"], str(body)[:120])
        novel = "暴雨压在林家演武场上。林风攥着扫帚站在场边。赵虎冷笑：“你也配站在这里？”苏婉撑着油纸伞站在廊下。"
        code, body = b.req("POST", "/api/novel/polish", {"project_id": pid, "text": novel, "person": "third"}, bearer=jwt)
        check("3e 替身 LLM（润色）", code == 200 and body["data"]["text"].startswith("（润色稿）"), str(body)[:120])
        code, text = b.req("POST", "/api/assets/extract-all", {"project_id": pid, "novel_text": novel}, bearer=jwt)
        check("3f 替身 LLM（提取资产，SSE）", code == 200 and '"done"' in str(text), str(text)[-120:])
        code, chars = b.req("GET", f"/api/characters?project_id={pid}", bearer=jwt)
        check("3g 提取出角色", code == 200 and len(chars) > 0, f"{code} {len(chars) if isinstance(chars, list) else chars}")
        if isinstance(chars, list) and chars:
            code, body = b.req("POST", "/api/assets/generate",
                               {"asset_type": "character", "asset_id": chars[0]["id"], "form_index": 0}, bearer=jwt)
            img = body["data"]["img_path"] if code == 200 else None
            check("3h 替身文生图（需随包夹具、Pillow）", code == 200 and img, f"{code} {str(body)[:150]}")
            if img:
                code, raw = b.req("GET", f"/static/{img}", token=False, raw=True)
                check("3i 静态文件可取回", code == 200 and raw[:4] == b"\x89PNG", f"{code} {len(raw)}B")
        # 内存
        time.sleep(1)
        main_rss = rss_mb(b.proc.pid)
        kids = b.children_rss()
        metrics["内存：后端进程 RSS（MB）"] = f"{main_rss:.0f}"
        metrics["内存：mongod RSS（MB）"] = f"{sum(kids.values()):.0f}" if kids else f"{sum(rss_mb(p) for p in mp):.0f}"
        # 4 SIGTERM
        mpid = mp[0]
        b.proc.send_signal(signal.SIGTERM)
        try:
            rc = b.proc.wait(30)
        except subprocess.TimeoutExpired:
            rc = None
        live.remove(b)
        check("4a SIGTERM 后后端退出", rc is not None, f"rc={rc}")
        check("4b SIGTERM 后 mongod 消失", wait_dead(mpid) and not mongod_pids(data), f"leftover={mongod_pids(data)}")
        check("4c mongod.pid 已清理", not pidfile.exists())

        # 5 kill -9
        b2 = Backend(exe, data, mongod)
        live.append(b2)
        check("5a 二次启动 ready（数据目录已有数据）", b2.wait_ready(), "")
        metrics["二次（热）启动到 ready（秒）"] = f"{getattr(b2, 'startup_s', -1):.1f}"
        old = mongod_pids(data)
        os.kill(b2.proc.pid, signal.SIGKILL)
        b2.proc.wait(10)
        live.remove(b2)
        time.sleep(1)
        orphan = [p for p in old if alive(p)]
        check("5b kill -9 后端后 mongod 确实遗留（复现孤儿）", len(orphan) == 1, f"orphan={orphan}")
        b3 = Backend(exe, data, mongod)
        live.append(b3)
        ok = b3.wait_ready()
        check("5c 再次启动成功", ok, "")
        check("5d 遗留 mongod 已被清理", bool(orphan) and wait_dead(orphan[0]), f"old={orphan}")
        new = mongod_pids(data)
        check("5e 现在只有一个新 mongod", len(new) == 1 and new != orphan, f"pids={new}")
        if ok:
            code, body = b3.req("POST", "/api/auth/login", {"username": user, "password": pwd})
            check("5f 重启后数据仍在（能用旧账号登录）", code == 200, f"{code}")
            code, body = b3.req("GET", "/api/projects", bearer=body["data"]["token"] if code == 200 else None)
            check("5g 重启后项目仍在", code == 200 and len(body) == 1, "")
        # 6 SIGINT
        b3.proc.send_signal(signal.SIGINT)
        try:
            rc = b3.proc.wait(30)
        except subprocess.TimeoutExpired:
            rc = None
        live.remove(b3)
        check("6 SIGINT 后后端和 mongod 都消失", rc is not None and all(wait_dead(p) for p in new), f"rc={rc}")
    finally:
        for b in live:
            try:
                os.killpg(b.proc.pid, signal.SIGKILL)
            except OSError:
                pass
        for p in mongod_pids(data):
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        print("\n== 指标 ==")
        for k, v in metrics.items():
            print(f"{k}: {v}")
        failed = [r for r in results if not r[1]]
        print(f"\n通过 {len(results) - len(failed)} / {len(results)}")
        if failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
