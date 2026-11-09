"""端到端测试库的准备与清理（scripts/e2e.sh 调用）

用法：
  python tests/e2e_db.py reset   # 清空测试库并放好替身视频账号
  python tests/e2e_db.py accounts  # 只重置替身视频账号的今日用量
  python tests/e2e_db.py drop    # 删除测试库
  python tests/e2e_db.py snapshot > before.json   # 记录主库 dongai 各集合文档数
  python tests/e2e_db.py check [before.json]       # 测试库是否还存在；与快照对比主库有无变化

连接串读 MONGODB_URL，库名读 MONGODB_DB_NAME（必须包含 e2e 或 test）。不打印连接串。
"""
import json
import os
import sys
from datetime import date

from pymongo import MongoClient


def _main_counts(client) -> dict:
    db = client["dongai"]
    return {c: db[c].estimated_document_count() for c in sorted(db.list_collection_names())}


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    name = os.environ.get("MONGODB_DB_NAME", "")
    if not name or name == "dongai" or not any(k in name for k in ("e2e", "test")):
        sys.exit(f"拒绝操作非测试库: {name!r}")
    client = MongoClient(os.environ["MONGODB_URL"], serverSelectionTimeoutMS=8000)

    if action in ("reset", "accounts"):
        if action == "reset":
            client.drop_database(name)
        db = client[name]
        today = str(date.today())
        for i in range(1, 4):
            acc_id = f"e2e_account_{i}"
            db.doubao_accounts.update_one({"id": acc_id}, {"$set": {
                "id": acc_id, "name": f"替身账号{i}", "profile_dir": "", "cookies": [],
                "enabled": True, "logged_in": True, "usage": {"date": today, "count": 0},
            }}, upsert=True)
        print(f"{'已重置测试库 ' + name + '，' if action == 'reset' else ''}放好 3 个替身视频账号（今日用量清零）")
    elif action == "drop":
        client.drop_database(name)
        print(f"已删除测试库 {name}")
    elif action == "snapshot":
        # 主库各集合文档数，跑完后对比，确认测试没有写进主库
        print(json.dumps(_main_counts(client)))
    elif action == "check":
        names = client.list_database_names()
        print(f"测试库 {name} 存在: {name in names}")
        if len(sys.argv) > 2:
            before = json.loads(open(sys.argv[2]).read() or "{}")
            after = _main_counts(client)
            diff = {k: (before.get(k, 0), after.get(k, 0)) for k in set(before) | set(after)
                    if before.get(k, 0) != after.get(k, 0)}
            if diff:
                print("主库 dongai 文档数有变化（可能来自同时在用的 :8000 服务）: "
                      + ", ".join(f"{k} {a}→{b}" for k, (a, b) in sorted(diff.items())))
            else:
                print(f"主库 dongai 各集合文档数与测试前一致（{len(after)} 个集合）")
    else:
        sys.exit(f"未知操作: {action}")


if __name__ == "__main__":
    main()
