"""重复角色：找出同一个人的两张卡、合并、改掉分镜里的旧名字（core/character_dedupe）。"""
import asyncio

from core import character_dedupe as CD
from core.asset_merge import plan_merge
from core.prompt_registry import build_messages

A = {"_id": 1, "name": "白衣阴冷男子", "gender": "male", "importance": "main", "face": "俊美阴冷", "image_path": "a.png"}
B = {"_id": 2, "name": "白衣男子", "gender": "male", "importance": "main", "face": "", "image_path": "b.png",
     "voice": "25岁男性，清澈"}
SHEN = {"_id": 3, "name": "沈砚", "gender": "male", "importance": "main"}
MASK = {"_id": 4, "name": "铁面具", "gender": "male", "importance": "main"}
GUARD = {"_id": 5, "name": "黑衣人", "gender": "male", "importance": "extra"}


class _LLM:
    def __init__(self, reply=None, fail=False):
        self.reply, self.fail = reply, fail

    async def chat_json(self, messages, **kw):
        if self.fail:
            raise RuntimeError("超时")
        return self.reply


def test_similar_names():
    assert CD.similar_names("白衣男子", "白衣阴冷男子") and CD.similar_names("老 王", "老王头")
    assert not CD.similar_names("沈砚", "铁面具") and not CD.similar_names("王", "王小明")      # 一个字太泛
    assert not CD.similar_names("男子", "白衣阴冷男子") and not CD.similar_names("沈砚", "沈砚")  # 占比太小 / 同名不归这里管


def test_rule_groups_and_suggested_keep():
    groups = CD.rule_groups([SHEN, A, MASK, B, GUARD])
    assert len(groups) == 1 and set(groups[0]["names"]) == {"白衣阴冷男子", "白衣男子"}
    assert groups[0]["keep"] == "白衣阴冷男子" and groups[0]["source"] == "rule"       # 都有图：资料全的那个
    assert CD.rule_groups([A, dict(B, gender="female")]) == []                          # 性别不同不算
    assert CD.suggest_keep([dict(A, image_path=None), B])["name"] == "白衣男子"          # 出过图的优先


def test_ai_groups_only_accepts_listed_names_and_survives_failure():
    reply = {"same": [{"names": ["铁面具", "沈砚"], "reason": "摘下面具后是沈砚"},
                      {"names": ["黑衣人", "不存在"], "reason": "x"}, {"names": ["沈砚", "黑衣人"]}, "坏数据"]}
    groups = asyncio.run(CD.ai_groups(_LLM(reply), [SHEN, MASK, GUARD], novel="……"))
    assert len(groups) == 1 and groups[0]["names"] == ["铁面具", "沈砚"] and groups[0]["source"] == "ai"
    assert asyncio.run(CD.ai_groups(_LLM(fail=True), [SHEN, MASK])) == []
    assert asyncio.run(CD.ai_groups(_LLM({}), [SHEN])) == []
    both = CD.combine(groups, CD.rule_groups([A, B]), groups)
    assert [g["source"] for g in both] == ["ai", "rule"]


def test_prompt_avoids_fake_provider_keywords():
    text = "\n".join(m["content"] for m in build_messages(CD.PROMPT_KEY, cast_block="x", novel_text="y"))
    for word in ('"segments"', '"shots"', '"characters"', '"scenes"', '"props"', '"dialogues"'):
        assert word not in text
    assert "【角色表】" in text


def test_merge_plan_keeps_images_fills_blanks_and_records_alias():
    update = CD.merge_plan(B, [A])
    assert update["face"] == "俊美阴冷" and "voice" not in update                  # 空的补上，填过的不动
    assert [(f["name"], f["image_path"]) for f in update["forms"]] == [("白衣男子", "b.png"), ("白衣阴冷男子", "a.png")]
    assert update["aliases"] == ["白衣阴冷男子"]
    no_image = CD.merge_plan(B, [dict(A, image_path=None)])
    assert "forms" not in no_image and no_image["aliases"] == ["白衣阴冷男子"]      # 没图的不带形态进来
    assert CD.merge_plan(GUARD, [SHEN])["importance"] == "main"                    # 戏份取重的


def test_rename_refs_in_shot_document():
    shot = {"_id": 9, "characters": ["白衣阴冷男子", "白衣男子", "沈砚"], "character_name": "白衣阴冷男子",
            "lines": [{"speaker": "白衣阴冷男子", "text": "白衣阴冷男子冷笑。"}],
            "beats": [{"action": "白衣阴冷男子展开折扇"}], "forms": {"白衣阴冷男子": "默认"},
            "img_path": "images/白衣阴冷男子.png", "duration": 10}
    out, changed = CD.rename_refs(shot, "白衣阴冷男子", "白衣男子")
    assert changed and out["characters"] == ["白衣男子", "沈砚"] and out["character_name"] == "白衣男子"
    assert out["lines"][0] == {"speaker": "白衣男子", "text": "白衣男子冷笑。"} and out["beats"][0]["action"] == "白衣男子展开折扇"
    assert out["forms"] == {"白衣男子": "默认"} and out["img_path"] == "images/白衣阴冷男子.png" and out["_id"] == 9
    assert CD.rename_refs({"a": "沈砚"}, "铁面具", "沈砚") == ({"a": "沈砚"}, False)
    assert CD.rename_refs("沈砚之与沈砚", "沈砚", "沈砚之")[0] == "沈砚之与沈砚之"   # 新名字包含旧名字：不重复替换


def test_reextract_merges_into_alias_owner():
    kept = dict(B, aliases=["白衣阴冷男子"], face="俊美阴冷")
    inserts, updates, skipped = plan_merge([kept], [{"name": "白衣阴冷男子", "face": "阴冷", "trait": "阴冷"}])
    assert inserts == [] and updates == [(kept, {"trait": "阴冷"})]
