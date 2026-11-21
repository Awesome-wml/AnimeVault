"""资产提取去重（core/asset_merge）：同名并入已有记录，不覆盖用户已有的内容和图。"""
import asyncio

from core.asset_merge import merge_doc, plan_merge, summary, upsert_assets


def test_merge_fills_blanks_only_and_never_touches_images():
    old = {"_id": 1, "name": "沈砚", "face": "用户改过的长相", "voice": "", "image_path": "images/a.png",
           "forms": [{"name": "雨夜负伤", "outfit": "深色短外套", "image_path": "images/f.png"}]}
    new = {"name": "沈砚", "face": "模型重新写的长相", "voice": "沉稳青年男声", "image_path": None, "gender": "male",
           "forms": [{"name": "雨夜负伤", "outfit": "模型重新写的穿搭", "image_path": None},
                     {"name": "常服", "outfit": "青色长衫", "image_path": None}]}
    change = merge_doc(old, new)
    assert change == {"voice": "沉稳青年男声", "gender": "male",
                      "forms": [old["forms"][0], {"name": "常服", "outfit": "青色长衫", "image_path": None}]}
    assert merge_doc(old, {"name": "沈砚", "face": "别的", "forms": [{"name": " 雨夜负伤 "}]}) == {}


def test_plan_merge_splits_into_insert_update_skip_and_dedupes_within_batch():
    existing = [{"_id": 1, "name": "沈砚", "face": "剑眉"}, {"_id": 2, "name": "铁面具", "face": ""}]
    docs = [{"name": "沈 砚", "face": "别的"},                       # 已存在、没新信息 → 跳过
            {"name": "铁面具", "face": "覆铁面具"},                   # 已存在、补空 → 合并
            {"name": "白衣男子", "face": "俊美"},                     # 新的
            {"name": "白衣男子", "face": "别的", "voice": "阴冷"},     # 同一批里重名 → 并进上一条
            {"name": "", "face": "没名字"}]
    inserts, updates, skipped = plan_merge(existing, docs)
    assert [d["name"] for d in inserts] == ["白衣男子"] and inserts[0]["voice"] == "阴冷" and inserts[0]["face"] == "俊美"
    assert updates == [(existing[1], {"face": "覆铁面具"})] and skipped == 1


class FakeCollection:
    def __init__(self, docs):
        self.docs, self.inserted, self.updated = list(docs), [], []

    def find(self, query):
        docs = [d for d in self.docs if d.get("project_id") == query["project_id"]]

        class Cursor:
            async def to_list(self, n):
                return docs
        return Cursor()

    async def insert_many(self, docs):
        self.inserted.extend(docs)

    async def update_one(self, query, change):
        self.updated.append((query["_id"], change["$set"]))


def test_upsert_only_looks_at_this_project_and_reports_counts():
    coll = FakeCollection([{"_id": 1, "project_id": "p1", "name": "沈砚", "description": ""},
                           {"_id": 9, "project_id": "p2", "name": "铁面具", "description": "别的作品的"}])
    r = asyncio.run(upsert_assets(coll, "p1", [{"project_id": "p1", "name": "沈砚", "description": "主角"},
                                              {"project_id": "p1", "name": "铁面具", "description": "反派"}]))
    assert r == {"added": 1, "merged": 1, "skipped": 0}
    assert [d["name"] for d in coll.inserted] == ["铁面具"] and coll.updated == [(1, {"description": "主角"})]
    assert asyncio.run(upsert_assets(coll, "p1", [])) == {"added": 0, "merged": 0, "skipped": 0}
    assert summary("角色", {"added": 2, "merged": 1, "skipped": 3}) == "角色新增 2、并入已有 1、已存在 3"
    assert summary("道具", {"added": 0, "merged": 0, "skipped": 0}) == "道具新增 0"
