"""内置提示词入库（T-216）：启动同步、取值顺序、提示词接口

同步与取值顺序直接对一个独立的测试库操作（库名带 e2e），不影响跑着的后端；
接口部分走 HTTP。
"""
import os
import uuid
from datetime import datetime

import pytest
from conftest import register

from core import builtin_prompts as B
from core import prompt_store
from core import llm_factory
from core.prompt_tpl import NOVEL_GENERATE_PROMPT, SHOT_SPLIT_SCRIPT_PROMPT


@pytest.fixture
def sdb(mongo, db_name):
    """每个用例一个干净的小库（名字含 e2e），用完即删"""
    name = f"{db_name}_sync_{uuid.uuid4().hex[:6]}"
    assert "e2e" in name or "test" in name
    db = mongo.client[name]
    yield db
    mongo.client.drop_database(name)


def _builtins(db):
    return {p["type"]: p for p in db.prompts.find({"is_builtin": True})}


# ---------- 同步 ----------

def test_builtin_table_matches_frontend_types():
    assert len(B.BUILTIN_PROMPTS) == 13
    assert "video" not in B.BUILTIN_TYPES
    for p in B.BUILTIN_PROMPTS:
        assert p["content"] and p["name"] and p["description"]


def test_sync_is_idempotent(sdb):
    s1 = B.sync_builtin_prompts(sdb)
    assert s1["inserted"] == 13 and s1["removed"] == 0
    rows = _builtins(sdb)
    assert set(rows) == set(B.BUILTIN_TYPES)
    for p in rows.values():
        assert p["category"] == "通用" and p["is_default"] is False and p["has_update"] is False
        assert p["builtin_hash"] == B.content_hash(p["content"])
    s2 = B.sync_builtin_prompts(sdb)
    assert s2 == {"inserted": 0, "updated": 0, "kept": 13, "removed": 0}
    assert sdb.prompts.count_documents({}) == 13


def test_sync_overwrites_unmodified_and_keeps_user_edits(sdb, monkeypatch):
    B.sync_builtin_prompts(sdb)
    novel = sdb.prompts.find_one({"type": "novel", "is_builtin": True})
    # 用户改了“小说润色”的正文（builtin_hash 仍是旧代码）
    sdb.prompts.update_one({"type": "novel_polish", "is_builtin": True}, {"$set": {"content": "我的润色模板 {novel_text}"}})

    # 模拟代码更新了这两个模板
    new_novel, new_polish = "新版生成小说 {genre}", "新版润色 {novel_text}"
    monkeypatch.setitem(B._BY_TYPE["novel"], "content", new_novel)
    monkeypatch.setitem(B._BY_TYPE["novel_polish"], "content", new_polish)
    stats = B.sync_builtin_prompts(sdb)
    assert stats["updated"] == 2 and stats["kept"] == 11

    # 未改动的记录被覆盖成新代码，_id 不变
    n = sdb.prompts.find_one({"type": "novel", "is_builtin": True})
    assert n["_id"] == novel["_id"] and n["content"] == new_novel and n["has_update"] is False
    assert n["builtin_hash"] == B.content_hash(new_novel)
    # 用户改过的保留，标记 has_update 并存最新代码
    p = sdb.prompts.find_one({"type": "novel_polish", "is_builtin": True})
    assert p["content"] == "我的润色模板 {novel_text}" and p["has_update"] is True
    assert p["latest_builtin"] == new_polish
    # 再同步一次不变
    assert B.sync_builtin_prompts(sdb)["kept"] == 13


def test_sync_cleans_legacy_placeholders_and_keeps_user_defaults(sdb):
    """旧库：is_builtin 的 video 占位、无 hash 的旧内置、用户自己设的默认"""
    old = datetime(2026, 11, 5)
    sdb.prompts.insert_many([
        {"name": "默认视频提示词", "type": "video", "content": "【硬性参数】15秒", "is_default": True, "is_builtin": True,
         "category": "通用", "created_at": old},
        {"name": "默认拆分校词", "type": "split_shots", "content": "你是一个专业的短剧分镜师...", "is_default": True,
         "is_builtin": True, "category": "通用", "created_at": old},
        {"name": "小说生成", "type": "novel", "content": "旧的小说提示词", "is_default": True, "is_builtin": True,
         "category": "通用", "created_at": old},
        {"name": "都市·角色提取", "type": "character_extract", "category": "都市", "content": "都市角色 {novel_text}",
         "is_default": True, "is_builtin": False, "created_at": old},
        {"name": "通用-分镜提取", "type": "split_shots", "category": "通用", "content": "我的分镜 {novel_paragraph}",
         "is_default": True, "created_at": old},
    ])
    stats = B.sync_builtin_prompts(sdb)
    assert stats["removed"] == 1 and stats["inserted"] == 11 and stats["updated"] == 2
    assert sdb.prompts.count_documents({"type": "video"}) == 0
    rows = _builtins(sdb)
    assert set(rows) == set(B.BUILTIN_TYPES)
    # 无 hash 的旧内置占位按“未改动”处理：内容换成代码，且不再是默认
    assert rows["novel"]["content"] == NOVEL_GENERATE_PROMPT and rows["novel"]["is_default"] is False
    assert rows["split_shots"]["name"] == "内置·拆分镜（小说）"
    # 非内置的用户默认原样保留
    assert sdb.prompts.find_one({"name": "都市·角色提取"})["is_default"] is True
    assert sdb.prompts.find_one({"name": "通用-分镜提取"})["is_default"] is True
    assert sdb.prompts.count_documents({"is_builtin": {"$ne": True}}) == 2


def test_sync_dedupes_duplicate_builtins(sdb):
    B.sync_builtin_prompts(sdb)
    first = sdb.prompts.find_one({"type": "novel", "is_builtin": True})
    sdb.prompts.insert_one({"type": "novel", "is_builtin": True, "content": "重复", "created_at": datetime.now()})
    stats = B.sync_builtin_prompts(sdb)
    assert stats["removed"] == 1
    assert [p["_id"] for p in sdb.prompts.find({"type": "novel", "is_builtin": True})] == [first["_id"]]


# ---------- 取值顺序 ----------

def test_prompt_resolution_order(sdb, monkeypatch):
    """prompt_id → 题材用户默认 → 通用用户默认 → 内置记录 → 代码常量"""
    monkeypatch.setattr(prompt_store, "_db", sdb)
    monkeypatch.setattr(llm_factory, "_db", sdb)
    get = lambda cat="", t="novel": llm_factory.resolve_prompt("", t, "代码常量", category=cat)

    # 第 5 层：库里什么都没有 → 代码常量
    assert get("玄幻") == "代码常量"
    # 第 4 层：内置记录
    B.sync_builtin_prompts(sdb)
    assert get("玄幻") == NOVEL_GENERATE_PROMPT
    # 内置记录是用户改过的版本也照样生效
    sdb.prompts.update_one({"type": "novel", "is_builtin": True}, {"$set": {"content": "改过的内置"}})
    assert get("玄幻") == "改过的内置"
    # 内置记录即使被标 is_default 也不算用户默认，不影响顺序
    sdb.prompts.update_one({"type": "novel", "is_builtin": True}, {"$set": {"is_default": True}})
    # 第 3 层：通用用户默认（旧数据没打分类也算通用）
    gid = sdb.prompts.insert_one({"type": "novel", "content": "通用用户默认", "is_default": True}).inserted_id
    assert get("玄幻") == "通用用户默认" and get("") == "通用用户默认"
    # 第 2 层：题材用户默认
    cid = sdb.prompts.insert_one({"type": "novel", "category": "玄幻", "content": "玄幻用户默认", "is_default": True,
                                  "is_builtin": False}).inserted_id
    assert get("玄幻") == "玄幻用户默认" and get("都市") == "通用用户默认"
    # 第 1 层：prompt_id 指定（哪条都行，包括内置记录）
    bid = sdb.prompts.find_one({"type": "novel", "is_builtin": True})["_id"]
    assert llm_factory.resolve_prompt(str(gid), "novel", "x", category="玄幻") == "通用用户默认"
    assert llm_factory.resolve_prompt(str(bid), "novel", "x", category="玄幻") == "改过的内置"
    assert llm_factory.resolve_prompt("not-an-id", "novel", "x", category="玄幻") == "玄幻用户默认"
    # 未设默认的非内置记录不参与
    sdb.prompts.update_many({"_id": {"$in": [gid, cid]}}, {"$set": {"is_default": False}})
    assert get("玄幻") == "改过的内置"


def test_split_shots_script_falls_back_to_split_shots_user_default(sdb, monkeypatch):
    """剧本版拆分镜：先认 split_shots_script 的用户默认，再认旧的 split_shots 用户默认，再到自己的内置记录"""
    monkeypatch.setattr(prompt_store, "_db", sdb)
    B.sync_builtin_prompts(sdb)
    get = lambda: prompt_store.get_prompt("split_shots_script", "代码", category="玄幻", alias_types=("split_shots",))
    assert get() == SHOT_SPLIT_SCRIPT_PROMPT
    sdb.prompts.insert_one({"type": "split_shots", "category": "通用", "content": "旧分镜默认", "is_default": True})
    assert get() == "旧分镜默认"
    sdb.prompts.insert_one({"type": "split_shots_script", "category": "通用", "content": "剧本分镜默认", "is_default": True})
    assert get() == "剧本分镜默认"


# ---------- 接口 ----------

def test_prompts_api_requires_login(client):
    assert client.get("/api/prompts").status_code == 403
    assert client.post("/api/prompts", json={"name": "x", "type": "novel", "content": "x"}).status_code == 403
    assert client.get("/api/prompts", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_prompts_list_has_builtins(client, user):
    r = client.get("/api/prompts", headers=user["headers"])
    assert r.status_code == 200
    rows = r.json()["data"]
    builtins = [p for p in rows if p["is_builtin"]]
    assert {p["type"] for p in builtins} == set(B.BUILTIN_TYPES)
    for p in builtins:
        assert p["has_update"] is False and p["category"] == "通用" and p["description"]
        assert "builtin_hash" not in p and "latest_builtin" not in p
    assert not any(p["type"] == "video" for p in rows)
    # 按类型筛选
    r = client.get("/api/prompts", params={"type": "novel"}, headers=user["headers"])
    assert all(p["type"] == "novel" for p in r.json()["data"])


def test_builtin_edit_restore_duplicate_delete(client, user, mongo):
    h = user["headers"]
    novel = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["is_builtin"])
    pid = novel["_id"]
    try:
        # 删内置被拒
        r = client.delete(f"/api/prompts/{pid}", headers=h)
        assert r.status_code == 400 and "内置" in r.json()["detail"]
        # 内置只允许改 content：其它字段被忽略
        r = client.put(f"/api/prompts/{pid}", json={"name": "改名", "is_default": True, "type": "novel_polish",
                                                    "content": "用户改的小说模板 {genre}"}, headers=h)
        assert r.status_code == 200 and r.json()["has_update"] is False
        cur = client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"]
        me = next(p for p in cur if p["_id"] == pid)
        assert me["content"] == "用户改的小说模板 {genre}" and me["name"] == novel["name"]
        assert me["is_default"] is False and me["type"] == "novel" and me["is_builtin"] is True
        assert client.put(f"/api/prompts/{pid}", json={"name": "只改名"}, headers=h).status_code == 400
        assert client.put(f"/api/prompts/{pid}", json={"content": "  "}, headers=h).status_code == 400

        # 模拟“代码已更新”：库里 hash 落后于代码
        mongo.prompts.update_one({"_id": __import__("bson").ObjectId(pid)}, {"$set": {"builtin_hash": "stale"}})
        r = client.put(f"/api/prompts/{pid}", json={"content": "再改一次"}, headers=h)
        assert r.json()["has_update"] is True
        me = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["_id"] == pid)
        assert me["has_update"] is True

        # 恢复内置
        r = client.post(f"/api/prompts/{pid}/restore", headers=h)
        assert r.status_code == 200 and r.json()["content"] == NOVEL_GENERATE_PROMPT
        me = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["_id"] == pid)
        assert me["content"] == NOVEL_GENERATE_PROMPT and me["has_update"] is False

        # 复制为自定义
        r = client.post(f"/api/prompts/{pid}/duplicate", json={"category": "玄幻"}, headers=h)
        assert r.status_code == 200
        cid = r.json()["id"]
        copy = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["_id"] == cid)
        assert copy["is_builtin"] is False and copy["is_default"] is False and copy["category"] == "玄幻"
        assert copy["name"] == novel["name"] + "（副本）" and copy["content"] == NOVEL_GENERATE_PROMPT
        # 自定义记录不能恢复内置；可以设默认、可以删
        assert client.post(f"/api/prompts/{cid}/restore", headers=h).status_code == 400
        assert client.put(f"/api/prompts/{cid}", json={"is_default": True}, headers=h).status_code == 200
        copy = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["_id"] == cid)
        assert copy["is_default"] is True and copy["category"] == "玄幻"
        assert client.delete(f"/api/prompts/{cid}", headers=h).status_code == 200
        assert client.delete(f"/api/prompts/{cid}", headers=h).status_code == 404
        # 新建时不能把自己标成内置
        r = client.post("/api/prompts", json={"name": "伪内置", "type": "novel", "content": "x", "is_builtin": True}, headers=h)
        nid = r.json()["id"]
        fake = next(p for p in client.get("/api/prompts", params={"type": "novel"}, headers=h).json()["data"] if p["_id"] == nid)
        assert fake["is_builtin"] is False
        client.delete(f"/api/prompts/{nid}", headers=h)
    finally:
        client.post(f"/api/prompts/{pid}/restore", headers=h)
