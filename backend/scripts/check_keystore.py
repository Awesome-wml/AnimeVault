"""手动验证真实系统钥匙串：写入 DongAI-selfcheck-* 临时条目、读回、删除；不触碰任何已有条目。

用法：cd backend && python scripts/check_keystore.py [--timeout 20]
系统若弹出授权窗口需要点允许；超时则报告并退出码 2。
"""
import argparse
import secrets
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.license_store import KeyringVault, SERVICE_NAME  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=20)
    args = ap.parse_args()
    account = "DongAI-selfcheck-" + secrets.token_hex(6)
    value = secrets.token_hex(16)
    result = {}

    def run():
        v = KeyringVault()
        try:
            v.set(account, value)
            result["written"] = True
            result["read_ok"] = v.get(account) == value
            result["backend"] = type(v._kr()).__module__
        except Exception as e:
            result["error"] = type(e).__name__
        finally:
            try:
                v.delete(account)
                result["deleted"] = v.get(account) is None
            except Exception as e:
                result["delete_error"] = type(e).__name__

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(args.timeout)
    if t.is_alive():
        print(f"超时（{args.timeout}s）：可能有授权窗口等待确认；条目 {SERVICE_NAME}/{account} 请手动检查")
        return 2
    print(result)
    ok = result.get("written") and result.get("read_ok") and result.get("deleted")
    print("钥匙串自检", "通过" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
