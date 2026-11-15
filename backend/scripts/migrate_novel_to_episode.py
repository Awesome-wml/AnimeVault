"""一次性迁移：小说 / 剧本从项目级归集到第一集名下。

背景：小说原先存在 projects.novel_content（项目级），scripts 只带 project_id；
改造为小说/剧本按集（video_set）归属后，把存量内容归到每个项目的第一集，
第二集及以后保持留空。脚本幂等，可重复执行；默认 dry-run，加 --apply 才写库。

用法：
    .venv-host/bin/python -m scripts.migrate_novel_to_episode          # 只打印计划
    .venv-host/bin/python -m scripts.migrate_novel_to_episode --apply  # 实际迁移
"""
import argparse
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

# 本地直连 localhost；容器内由环境变量 MONGODB_URL 覆盖。
MONGO_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017/")
MONGO_DB = os.environ.get("MONGODB_DB_NAME", "dongai")


async def migrate(apply: bool) -> None:
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[MONGO_DB]

    projects = await db.projects.find({}).to_list(None)
    moved_novel = moved_scripts = 0

    for p in projects:
        pid = str(p["_id"])
        sets = await db.video_sets.find({"project_id": pid}).sort("order", 1).to_list(None)
        if not sets:
            print(f"[跳过] 项目 {p.get('name')} ({pid[:8]}) 没有集数")
            continue
        first = sets[0]
        first_id = str(first["_id"])

        # 1) 项目级小说 → 第一集（第一集已有小说则保留，不覆盖）
        novel = (p.get("novel_content") or "").strip()
        if novel:
            first_novel = (first.get("novel_content") or "").strip()
            if not first_novel:
                print(f"[小说] {p.get('name')}: {len(novel)} 字 → 第一集《{first.get('name')}》")
                if apply:
                    await db.video_sets.update_one(
                        {"_id": first["_id"]}, {"$set": {"novel_content": p["novel_content"]}}
                    )
                moved_novel += 1
            else:
                print(f"[小说] {p.get('name')}: 第一集已有小说，保留不覆盖")
            # 项目级冗余正文清掉，避免双份混淆
            if apply:
                await db.projects.update_one({"_id": p["_id"]}, {"$unset": {"novel_content": ""}})

        # 2) 未归集的剧本场次 → 第一集
        orphans = await db.scripts.find(
            {"project_id": pid, "video_set_id": {"$exists": False}}
        ).to_list(None)
        if orphans:
            print(f"[剧本] {p.get('name')}: {len(orphans)} 场 → 第一集《{first.get('name')}》")
            if apply:
                await db.scripts.update_many(
                    {"project_id": pid, "video_set_id": {"$exists": False}},
                    {"$set": {"video_set_id": first_id}},
                )
            moved_scripts += len(orphans)

    print(f"\n{'已写入' if apply else 'dry-run，未写入'}：小说 {moved_novel} 份，剧本 {moved_scripts} 场")
    cli.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小说/剧本归集到第一集")
    parser.add_argument("--apply", action="store_true", help="实际写库；不加则只打印计划")
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply))
