"""音色设计：每个角色一份声音设定，全片照这一份说话（core/voice_design）。"""
import asyncio
from pathlib import Path

from core import voice_design as VD
from core import video_prompt as VP
from core.knowledge import segment_knowledge
from core.prompt_registry import build_messages
from core.video_models import get_video_model
from core.voice_matcher import match_voices

SHEN = {"name": "沈砚", "gender": "male", "age_group": "少年", "trait": "阳光", "importance": "main",
        "voice": "17岁男性，清亮", "face": "少年，剑眉"}
ZHAO = {"name": "赵虎", "gender": "male", "age_group": "中年", "trait": "阴冷", "importance": "support",
        "voice": "40岁男性，沙哑", "face": "中年，刀疤"}
DESIGN = {"pitch": "偏高", "timbre": "清亮带少年气", "pace": "偏快", "manner": "语气上扬，句尾干脆", "habit": ""}


def _seg(**kw):
    seg = {"shot_no": 1, "duration": 10, "scene": "演武场", "characters": ["沈砚", "赵虎"],
           "lines": [{"speaker": "沈砚", "text": "我不服。", "kind": "onscreen", "start": 0.5, "end": 2},
                     {"speaker": "旁白", "text": "没有人回答他。", "kind": "narration", "start": 3, "end": 5}],
           "beats": [{"start": 0, "end": 5, "shot_size": "中景", "action": "沈砚抬头", "lines": [1, 2]},
                     {"start": 5, "end": 10, "shot_size": "近景", "action": "赵虎冷笑", "lines": []}]}
    seg.update(kw)
    return seg


class _LLM:
    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.messages = reply, fail, None

    async def chat_json(self, messages, **kw):
        self.messages = messages
        if self.fail:
            raise RuntimeError("超时")
        return self.reply


def test_normalize_design_snaps_levels_and_strips_quotes():
    d = VD.normalize_design({"pitch": "偏高一点", "timbre": "“清亮”带少年气，", "pace": "语速较快", "manner": "x" * 60})
    assert d["pitch"] == "偏高" and d["pace"] == "快" and d["timbre"] == "清亮带少年气" and len(d["manner"]) == 24
    assert VD.normalize_design({}) is None and VD.normalize_design("清亮") is None
    assert VD.normalize_design({"pitch": "", "timbre": " "}) is None


def test_voice_line_is_stable_and_falls_back_to_old_text():
    c = dict(SHEN, voice_design=DESIGN)
    line = VD.voice_line(c)
    assert line == "少年声，音高偏高，清亮带少年气，语速偏快，语气上扬，句尾干脆"
    assert VD.voice_line(c) == line and len(line) <= VD.MAX_LINE
    assert VD.voice_line(SHEN) == "17岁男性，清亮"           # 没设计过：用提取时写的原话
    assert VD.voice_line({"name": "路人"}) == ""
    long = dict(SHEN, voice_design=dict(DESIGN, manner="咬字用力" * 6, habit="开口前先顿半拍"))
    got = VD.voice_line(long)
    assert len(got) <= VD.MAX_LINE and got.endswith("咬字用力") and "顿半拍" not in got   # 放不下的整项不写，不截半句


def test_fallback_design_differs_by_age_and_trait():
    a, b = VD.fallback_design(SHEN), VD.fallback_design(ZHAO)
    assert a["pitch"] == "偏高" and a["timbre"] == "清亮" and a["pace"] == "偏快"
    assert b["pitch"] == "偏低" and b["timbre"] == "沙哑"
    plain = VD.fallback_design({"name": "x", "gender": "female", "age_group": "暮年", "voice": "70岁女性，低柔"})
    assert plain["pitch"] == "偏低" and plain["timbre"] == "低柔" and plain["pace"] == "偏慢"


def test_clashes_flags_same_gender_pitch_timbre():
    same = [dict(SHEN, voice_design=DESIGN), dict(ZHAO, voice_design=DESIGN)]
    assert len(VD.clashes(same)) == 1 and "沈砚、赵虎" in VD.clashes(same)[0]
    assert VD.clashes([dict(SHEN, voice_design=DESIGN), dict(ZHAO, voice_design=dict(DESIGN, pitch="低沉"))]) == []
    assert VD.clashes([dict(SHEN, voice_design=DESIGN), dict(ZHAO, voice_design=DESIGN, importance="extra")]) == []


def test_pick_cast_keeps_user_and_existing_ai():
    user = dict(SHEN, voice_design=DESIGN, voice_design_source="user")
    ai = dict(ZHAO, voice_design=DESIGN, voice_design_source="ai")
    new = {"name": "苏婉", "importance": "extra"}
    assert [c["name"] for c in VD.pick_cast([new, user, ai])] == ["苏婉"]
    assert [c["name"] for c in VD.pick_cast([new, user, ai], overwrite=True)] == ["赵虎", "苏婉"]   # 手改的始终不动


def test_design_cast_parses_reply_and_shows_fixed_voices():
    fixed = dict(ZHAO, voice_design=dict(DESIGN, pitch="低沉", timbre="沙哑"), voice_design_source="user")
    llm = _LLM({"narrator": "沉厚中年男声", "voices": [
        dict(DESIGN, name="沈砚"), {"name": "不存在的人", "pitch": "低沉"}, "坏数据"]})
    out, narrator, note = asyncio.run(VD.design_cast(llm, [SHEN, fixed], [SHEN], novel="沈砚抬头。"))
    assert list(out) == ["沈砚"] and out["沈砚"]["pitch"] == "偏高" and narrator == "沉厚中年男声" and note == ""
    text = "\n".join(m["content"] for m in llm.messages)
    assert "- 沈砚（主角，男，少年，阳光）" in text and "- 赵虎：中年男声，音高低沉，沙哑" in text and "沈砚抬头。" in text


def test_design_cast_failure_returns_empty_with_note():
    out, narrator, note = asyncio.run(VD.design_cast(_LLM(fail=True), [SHEN], [SHEN]))
    assert out == {} and narrator == "" and "基础设定" in note
    out, _, note = asyncio.run(VD.design_cast(_LLM({}), [SHEN], [SHEN]))
    assert out == {} and note
    assert asyncio.run(VD.design_cast(_LLM(fail=True), [SHEN], [])) == ({}, "", "")


def test_prompt_avoids_fake_provider_keywords():
    text = "\n".join(m["content"] for m in build_messages(VD.PROMPT_KEY, cast_block="x", fixed_block="y", novel_text="z"))
    for word in ('"segments"', '"shots"', '"characters"', '"scenes"', '"props"', '"dialogues"'):
        assert word not in text
    assert "【待设计角色】" in text and '"voices"' in text


def test_segment_knowledge_carries_speaker_voices_and_narrator():
    chars = [dict(SHEN, voice_design=DESIGN), ZHAO]
    k = segment_knowledge(_seg(), chars, [], [], narrator="沉厚中年男声")
    assert k["voices"] == {"沈砚": VD.voice_line(chars[0])} and k["narrator"] == "沉厚中年男声"   # 赵虎没台词，不列


def test_video_prompt_writes_same_voice_line_in_every_segment(tmp_path: Path):
    chars = [dict(SHEN, voice_design=DESIGN), dict(ZHAO, voice_design=dict(DESIGN, pitch="低沉", timbre="沙哑"))]
    model = get_video_model(None)
    one = VP.build_upload_plan(_seg(), chars, [], [], tmp_path, model, narrator="沉厚中年男声")["prompt"]
    two = VP.build_upload_plan(_seg(shot_no=2, scene="后山", lines=[
        {"speaker": "沈砚", "text": "再来。", "kind": "onscreen", "start": 0.5, "end": 1.5}],
        beats=[{"start": 0, "end": 10, "shot_size": "中景", "action": "沈砚握拳", "lines": [1]}]),
        chars, [], [], tmp_path, model)["prompt"]
    line = f"沈砚：{VD.voice_line(chars[0])}"
    for prompt in (one, two):
        assert f"【声音设定】{line}。{VP.VOICE_RULE}\n【台词清单】" in prompt
    assert "赵虎：" not in one.split("【声音设定】")[1].split("\n")[0]          # 这一段没开口的人不写
    assert "旁白（沉厚中年男声）" in one and "统一使用沉厚中年男声" in one and VP.NARRATOR_VOICE not in one


def test_video_prompt_without_voice_settings_is_unchanged(tmp_path: Path):
    bare = [{"name": "沈砚", "face": "少年"}]
    prompt = VP.build_upload_plan(_seg(), bare, [], [], tmp_path, get_video_model(None))["prompt"]
    assert "【声音设定】" not in prompt and f"旁白（{VP.NARRATOR_VOICE}）" in prompt


def test_narrator_line_default_and_custom():
    assert VD.narrator_line(None) == VD.DEFAULT_NARRATOR == VP.NARRATOR_VOICE
    assert VD.narrator_line({"narrator_voice": " 清冷女声 "}) == "清冷女声"


def test_library_match_uses_design_words():
    villain = dict(ZHAO, trait="", voice_design={"pitch": "偏低", "timbre": "阴冷", "pace": "慢", "manner": "带邪气", "habit": ""})
    plain = dict(ZHAO, trait="")
    assert match_voices([villain])[0]["voice"] == "zh_male_yinleng"
    assert match_voices([plain])[0]["voice"] != "zh_male_yinleng"


# ---------- 提取角色后自动设计 ----------
class _Coll:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        docs = self.docs

        class Cursor:
            async def to_list(self, length=None):
                return docs
        return Cursor()

    async def update_one(self, query, change):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                d.update(change["$set"])


class _DB:
    def __init__(self, chars, project):
        self.characters, self.projects = _Coll(chars), _Coll([project])


def test_auto_design_after_extract_fills_everyone_and_keeps_user_edits():
    from api.character import auto_design_voices
    user_set = dict(ZHAO, _id=2, voice_design=dict(DESIGN, pitch="低沉"), voice_design_source="user")
    chars = [dict(SHEN, _id=1), user_set, {"_id": 3, "name": "苏婉", "gender": "female", "age_group": "青年", "importance": "support"}]
    project = {"_id": "p1", "genre": "玄幻"}
    db = _DB(chars, project)
    llm = _LLM({"narrator": "清冷女声", "voices": [dict(DESIGN, name="沈砚")]})
    note = asyncio.run(auto_design_voices(db, llm, "u1", project, novel="沈砚抬头。"))
    assert "为 1 个角色设计了声音" in note and "1 个按年龄和气质给了基础设定" in note
    assert chars[0]["voice_design_source"] == "ai" and chars[2]["voice_design_source"] == "rule"
    assert chars[1]["voice_design"]["pitch"] == "低沉" and chars[1]["voice_design_source"] == "user"   # 手改的不动
    assert project["narrator_voice"] == "清冷女声" and all(c.get("voice_name") for c in chars)
    # 再提取一次：AI 设计过的不重做，按规则推的那个再让模型试一次
    again = _LLM({"voices": [dict(DESIGN, name="苏婉", pitch="高亮")]})
    asyncio.run(auto_design_voices(db, again, "u1", project))
    todo_part, fixed_part = again.messages[-1]["content"].split("【待设计角色】")[-1].split("【已经定下的声音】")[:2]
    assert "- 苏婉" in todo_part and "- 沈砚" not in todo_part and "- 沈砚：" in fixed_part
    assert chars[2]["voice_design_source"] == "ai" and chars[0]["voice_design"]["pitch"] == "偏高"
    assert project["narrator_voice"] == "清冷女声"


def test_auto_design_failure_does_not_break_extract():
    from api.character import auto_design_voices
    chars = [dict(SHEN, _id=1)]
    project = {"_id": "p1"}
    note = asyncio.run(auto_design_voices(_DB(chars, project), _LLM(fail=True), "u1", project))
    assert chars[0]["voice_design_source"] == "rule" and "基础设定" in note     # 模型挂了：有兜底，提取照常
    assert asyncio.run(auto_design_voices(None, _LLM(), "u1", project)).startswith("音色没能自动设计")
