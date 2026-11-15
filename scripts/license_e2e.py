#!/usr/bin/env python3
"""授权链路端到端验收（L-29），可重复运行。

走完：admin 签发授权码 -> 客户端取机器码 -> 激活 -> 续租 -> 业务接口可用 -> admin 停用（只读）/ 恢复 ->
换机（机器码不符）被拒 -> 重复会话（同一授权在另一实例激活）旧会话被顶掉 -> admin 吊销 -> 客户端完全拦截。
降级规则见 docs/license-design.md 第 6.3/7.3 节和 docs/license-client.md「各状态下功能可用性」。

真实组件：license-server（进程内 uvicorn，存储 memory 或临时 mongod）、admin HTTP API、
客户端后端（默认源码 + 最小应用 backend/tests/license_e2e_app.py；--exe 则是测试构建的桌面可执行文件）。
密钥对每次运行临时生成（私钥只在临时目录，结束即删）；--exe 时必须用构建时那把测试公钥对应的私钥（--priv-key）。

用法（用装了依赖的 Python）：
    ~/.local/dongai-venv/bin/python scripts/license_e2e.py [--store memory|mongo] [--exe PATH --priv-key FILE]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from license_e2e_lib import (ROOT, Checker, LicenseServer, TempMongod, find_mongod, free_port,  # noqa: E402
                             http_json, new_tmp)

from dongai_license import crypto  # noqa: E402
from dongai_license.machine_code import format_machine_code  # noqa: E402


class ClientBackend:
    """一个被测的客户端后端实例（源码最小应用，或桌面可执行文件）。"""

    def __init__(self, work: Path, name: str, keys: dict, server_url: str, exe: Path | None, mongod: str | None):
        self.name, self.exe = name, exe
        self.data = work / f"data-{name}"
        self.home = work / f"home-{name}"
        self.data.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        self.keys, self.server_url, self.mongod = keys, server_url, mongod
        self.proc = None
        self.token = None
        self.jwt = None
        self.renew_times: list[float] = []
        self.start()

    def start(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DONGAI_", "MONGODB_")) and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env.update({"HOME": str(self.home), "DONGAI_DATA_DIR": str(self.data), "NO_PROXY": "127.0.0.1,localhost"})
        if self.exe:
            env.update({"DONGAI_DESKTOP": "1", "DONGAI_FAKE_PROVIDERS": "1"})
            if self.mongod:
                env["DONGAI_MONGOD_BIN"] = self.mongod
            cmd, cwd = [str(self.exe)], None
        else:
            self.port = free_port()
            env.update({"DONGAI_LICENSE_ENFORCE": "1", "DONGAI_LICENSE_DEV": "1", "DONGAI_LICENSE_STORE": "file",
                        "DONGAI_LICENSE_PUBKEYS": json.dumps(self.keys), "DONGAI_LICENSE_SERVER": self.server_url,
                        "PYTHONPATH": f"{ROOT / 'backend'}:{ROOT / 'backend' / 'tests'}"})
            cmd = [sys.executable, "-m", "uvicorn", "license_e2e_app:app", "--host", "127.0.0.1",
                   "--port", str(self.port), "--log-level", "warning"]
            cwd = str(ROOT / "backend")
        self.lines: list[str] = []
        self._ready = threading.Event()
        self.proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        if self.exe:
            if not self._ready.wait(120):
                raise RuntimeError("桌面后端 120 秒内没有 ready：\n" + "\n".join(self.lines[-30:]))
        else:
            end = time.time() + 30
            while time.time() < end:
                try:
                    if self.req("GET", "/health")[0] == 200:
                        return
                except OSError:
                    pass
                time.sleep(0.3)
            raise RuntimeError("源码后端没有启动：\n" + "\n".join(self.lines[-30:]))

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())
            if self.exe and line.startswith("{"):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("event") == "ready":
                    self.port, self.token = d["port"], d["token"]
                    self._ready.set()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)

    def req(self, method, path, body=None, bearer=None):
        h = {}
        if self.token:
            h["X-DongAI-Local-Token"] = self.token
        if bearer:
            h["Authorization"] = "Bearer " + bearer
        return http_json(method, f"http://127.0.0.1:{self.port}{path}", body, h, timeout=60)

    # ---- 授权接口
    def status(self):
        return self.req("GET", "/api/license/status")[1]

    def renew_now(self):
        """手动续租有「每分钟 3 次」限制：本实例最近 60 秒已有 3 次就等一等。"""
        now = time.time()
        self.renew_times = [t for t in self.renew_times if now - t < 62]
        if len(self.renew_times) >= 3:
            wait = 62 - (now - self.renew_times[0])
            print(f"    （续租限频：等 {wait:.0f} 秒）", flush=True)
            time.sleep(max(wait, 0))
        self.renew_times.append(time.time())
        return self.req("POST", "/api/license/renew-now")

    def activate(self, code):
        return self.req("POST", "/api/license/activate", {"code": code})

    # ---- 业务接口
    def login_business(self):
        """桌面模式业务接口还要账号 JWT（授权通过后才能注册/登录）。源码最小应用不需要。"""
        if not self.exe:
            return
        u, p = "e2e_user", "e2e-pass-123"
        self.req("POST", "/api/auth/register", {"username": u, "password": p})
        code, d = self.req("POST", "/api/auth/login", {"username": u, "password": p})
        assert code == 200, (code, d)
        self.jwt = d["data"]["token"]

    def biz_read(self):
        return self.req("GET", "/api/projects", bearer=self.jwt)

    def biz_write(self):
        return self.req("POST", "/api/projects", {"name": "e2e-项目", "genre": "玄幻"}, bearer=self.jwt)


def code_of(resp):
    return resp[1].get("code") if isinstance(resp[1], dict) else None


def run_flow(ck: Checker, ls: LicenseServer, work: Path, keys: dict, exe: Path | None, mongod: str | None):
    mk = lambda n: ClientBackend(work, n, keys, ls.url, exe, mongod)  # noqa: E731
    backends = []
    try:
        A = mk("A")
        backends.append(A)
        # 0 未激活
        st = A.status()
        ck.check("0a 未激活：status.state=unactivated", st.get("state") == "unactivated", f"state={st.get('state')}")
        r = A.biz_read()
        ck.check("0b 未激活：业务接口被完全拦截", r[0] == 403 and code_of(r) == "LICENSE_REQUIRED", f"{r[0]} {code_of(r)}")
        # 1 机器码
        code, d = A.req("GET", "/api/license/machine-code")
        mc = d.get("machine_code") if isinstance(d, dict) else None
        ck.check("1 客户端取机器码", code == 200 and mc, f"machine_code={mc}")
        # 2 签发
        lic = ls.issue(mc)
        lid, auth_code = lic["lid"], lic["code"]
        ck.check("2 admin 签发授权码", lic["status"] == "pending" and auth_code, f"lid={lid} status={lic['status']} code前16位={auth_code[:16]}…")
        # 3 激活：先试一个乱码
        r = A.activate("AAAAA-BBBBB-CCCCC")
        ck.check("3a 乱码授权码被拒", r[0] == 400 and code_of(r) == "LICENSE_INVALID", f"{r[0]} {code_of(r)}")
        r = A.activate(auth_code)
        st = A.status()
        ck.check("3b 激活成功", r[0] == 200 and st.get("state") == "valid", f"{r[0]} state={st.get('state')} plan={st.get('plan')}")
        _, ld = ls.admin("GET", f"/licenses/{lid}")
        _, dv = ls.admin("GET", f"/licenses/{lid}/devices")
        ck.check("3c 服务端：授权 active、绑定 1 台设备", ld.get("status") == "active" and len(dv["items"]) == 1,
                 f"status={ld.get('status')} devices={len(dv['items'])}")
        A.login_business()
        # 4 续租
        lease0 = st.get("lease_expires_at")
        time.sleep(1.2)
        r = A.renew_now()
        st = A.status()
        ck.check("4 续租成功，租约有效期向后推", r[0] == 200 and st["state"] == "valid" and st.get("lease_expires_at", 0) >= (lease0 or 0),
                 f"{r[0]} state={st['state']} lease_exp {lease0} -> {st.get('lease_expires_at')}")
        # 5 业务接口
        rr, rw = A.biz_read(), A.biz_write()
        ck.check("5 业务接口可用（读和写都放行）", rr[0] == 200 and rw[0] == 200, f"GET={rr[0]} POST={rw[0]}")
        # 6 停用 -> 只读
        c, d = ls.admin("POST", f"/licenses/{lid}/suspend")
        ck.check("6a admin 停用授权", c == 200 and d["status"] == "suspended", f"{c} {d.get('status')}")
        r = A.renew_now()
        st = A.status()
        ck.check("6b 客户端续租被拒：LICENSE_SUSPENDED，state=suspended 且 readonly", code_of(r) == "LICENSE_SUSPENDED"
                 and st["state"] == "suspended" and st.get("readonly"), f"{r[0]} {code_of(r)} state={st['state']} readonly={st.get('readonly')}")
        rr, rw = A.biz_read(), A.biz_write()
        ck.check("6c 只读降级：读 200，写 403 LICENSE_READONLY", rr[0] == 200 and rw[0] == 403 and code_of(rw) == "LICENSE_READONLY",
                 f"GET={rr[0]} POST={rw[0]} {code_of(rw)}")
        if not exe:  # 重启后仍是只读（服务端拒绝已落盘）
            A.stop()
            A.start()
            st = A.status()
            rw = A.biz_write()
            ck.check("6d 重启后仍然只读（状态已落盘）", st["state"] == "suspended" and rw[0] == 403, f"state={st['state']} POST={rw[0]}")
        # 7 恢复
        c, d = ls.admin("POST", f"/licenses/{lid}/resume")
        r = A.renew_now()
        st = A.status()
        rw = A.biz_write()
        ck.check("7 admin 恢复 -> 续租成功，写操作恢复", c == 200 and r[0] == 200 and st["state"] == "valid" and rw[0] == 200,
                 f"resume={c} renew={r[0]} state={st['state']} POST={rw[0]}")
        # 8 换机：授权码是别的机器的
        other_mc = format_machine_code(["9f01" + "ab" * 6, "9f02" + "ab" * 6, "9f03" + "ab" * 6])
        lic2 = ls.issue(other_mc)
        C = mk("C")
        backends.append(C)
        r = C.activate(lic2["code"])
        st = C.status()
        rr = C.biz_read()
        ck.check("8a 换机（授权码绑定的是另一台机器）：客户端拒绝激活", r[0] == 403 and code_of(r) == "LICENSE_MACHINE_MISMATCH"
                 and st["state"] == "unactivated" and rr[0] == 403, f"{r[0]} {code_of(r)} state={st['state']} biz={rr[0]}")
        code, d = http_json("POST", ls.url + "/license/v1/activate", {
            "license_code": auth_code, "machine_components": ["deadbeef01", "deadbeef02", "deadbeef03"], "app_version": "e2e"})
        ck.check("8b 服务端直接验证：同一授权码带别的机器分量激活被拒", code == 403 and d.get("code") == "LICENSE_MACHINE_MISMATCH", f"{code} {d.get('code')}")
        C.stop()
        # 9 重复会话
        B = mk("B")
        backends.append(B)
        r = B.activate(auth_code)
        stB = B.status()
        ck.check("9a 同机另一个实例用同一授权码激活（后激活者胜）", r[0] == 200 and stB["state"] == "valid", f"{r[0]} state={stB['state']}")
        r = A.renew_now()
        st = A.status()
        rr = A.biz_read()
        ck.check("9b 旧会话续租被拒 LICENSE_SESSION_CONFLICT，被完全拦截", code_of(r) == "LICENSE_SESSION_CONFLICT"
                 and st["state"] == "session_conflict" and rr[0] == 403 and code_of(rr) == "LICENSE_REQUIRED",
                 f"renew={r[0]} {code_of(r)} state={st['state']} biz={rr[0]} {code_of(rr)}")
        r = A.activate(auth_code)
        st = A.status()
        rB = B.renew_now()
        ck.check("9c 旧会话重新激活后又换对方被顶掉（同一授权同时只有一个在线会话）", r[0] == 200 and st["state"] == "valid"
                 and code_of(rB) == "LICENSE_SESSION_CONFLICT", f"A activate={r[0]} state={st['state']} B renew={code_of(rB)}")
        _, dv = ls.admin("GET", f"/licenses/{lid}/devices")
        ck.check("9d 服务端设备仍只有 1 台（两个实例同一机器分量）", len(dv["items"]) == 1, f"devices={len(dv['items'])}")
        B.stop()
        # 10 吊销 -> 完全拦截
        c, d = ls.admin("POST", f"/licenses/{lid}/revoke")
        r = A.renew_now()
        st = A.status()
        rr, rw = A.biz_read(), A.biz_write()
        ck.check("10a admin 吊销 -> 续租被拒 LICENSE_REVOKED，state=revoked", c == 200 and code_of(r) == "LICENSE_REVOKED" and st["state"] == "revoked",
                 f"revoke={c} renew={r[0]} {code_of(r)} state={st['state']}")
        ck.check("10b 吊销后完全拦截：读写都是 403 LICENSE_REQUIRED", rr[0] == 403 and rw[0] == 403
                 and code_of(rr) == code_of(rw) == "LICENSE_REQUIRED", f"GET={rr[0]} {code_of(rr)} POST={rw[0]} {code_of(rw)}")
        r = A.activate(auth_code)
        ck.check("10c 吊销后原授权码无法再次激活", r[0] == 403 and code_of(r) == "LICENSE_REVOKED", f"{r[0]} {code_of(r)}")
        # 11 审计
        _, ev = ls.admin("GET", f"/licenses/{lid}/events?order=asc&page_size=100")
        types = [e["type"] for e in ev["items"]]
        need = {"issued", "activated", "suspended", "resumed", "session_replaced", "revoked"}
        ck.check("11 服务端事件留痕", need <= set(types), f"events={types}")
    finally:
        for b in backends:
            b.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=["memory", "mongo"], default="memory", help="license-server 存储；mongo 会起临时 mongod")
    ap.add_argument("--exe", default="", help="测试构建的桌面可执行文件；不带则用源码最小应用")
    ap.add_argument("--priv-key", default="", help="--exe 时必填：与构建时 --test-public-key 对应的私钥文件")
    ap.add_argument("--mongod", default="", help="mongod 路径（默认自动找）")
    args = ap.parse_args()

    work = new_tmp("dongai-l29-e2e-")
    ck = Checker()
    mg = ls = None
    exe = Path(args.exe) if args.exe else None
    try:
        mongod_bin = args.mongod or find_mongod()
        if exe:
            if not args.priv_key:
                sys.exit("--exe 需要 --priv-key")
            bi = json.loads(subprocess.run([str(exe), "--build-info"], capture_output=True, text=True, timeout=120,
                                           env={**os.environ, "DONGAI_DATA_DIR": str(work / "bi")}).stdout.strip().splitlines()[-1])
            if not bi.get("test_build"):
                sys.exit("该可执行文件不是测试构建（--build-info 的 test_build 为 false），拒绝运行")
            print("被测构建：", json.dumps(bi, ensure_ascii=False))
            priv = Path(args.priv_key)
            port = urlparse(bi["license_server"]).port
        else:
            priv = work / "priv.key"
            subprocess.run([sys.executable, str(ROOT / "license" / "scripts" / "gen_keys.py"), "--out", str(priv)],
                           check=True, capture_output=True)
            port = 0
        store_url = None
        if args.store == "mongo":
            if not mongod_bin:
                sys.exit("找不到 mongod，无法跑 --store mongo")
            mg = TempMongod(mongod_bin, work)
            store_url = mg.url
        ls = LicenseServer(priv, args.store, store_url, port=port)
        print(f"license-server：{ls.url}  store={args.store}  kid={ls.kid}", flush=True)
        run_flow(ck, ls, work, {ls.kid: ls.public_key}, exe, mongod_bin)
    finally:
        if ls:
            ls.stop()
        if mg:
            mg.stop()
        shutil.rmtree(work, ignore_errors=True)
    failed = ck.failed
    print(f"\n通过 {len(ck.results) - len(failed)} / {len(ck.results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
