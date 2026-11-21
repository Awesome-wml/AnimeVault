"""拆分镜（T-204）：长文分块、紧凑输出展开、跨块合并编号、截断快速失败与缩块重试、
画面描述由代码组装、智谱始终思考模型自动切 thinking=low。"""
import asyncio
import json

import httpx
import pytest

from core import shot_timing as ST
from core import shot_split as SS
from core.providers import fake
from core.providers import llm_provider as LP
from core.providers import model_caps as MC
from core.providers.llm_provider import DoubaoLLMProvider, LLMRequestError, LLMTruncatedError
from core.video_models import get_video_model
from core.video_prompt import assemble_video_prompt

FAST = get_video_model()


@pytest.fixture(autouse=True)
def _real_providers(monkeypatch):
    """本文件的 provider 单测用 MockTransport 模拟接口；e2e 脚本开了替身开关，这里在本进程内关掉。"""
    monkeypatch.delenv("DONGAI_FAKE_PROVIDERS", raising=False)


def run(coro):
    return asyncio.run(coro)


# ---------- 分块 ----------
def _novel(n_sent=120):
    parts = []
    for i in range(n_sent):
        if i % 4 == 1:
            parts.append(f"“这是第{i}句台词，你听好了，我说完了。”")
        else:
            parts.append(f"这是第{i}句叙述，人物在包厢里慢慢转着酒杯。")
    return "".join(parts)


def test_chunks_no_mid_sentence_and_within_limit():
    text = _novel()
    chunks = SS.split_novel_chunks(text, 600)
    assert "".join(chunks) == text  # 不丢字、不重复
    assert len(chunks) == -(-len(text) // 600) and all(len(c) <= 600 for c in chunks)
    for c in chunks[:-1]:
        assert c[-1] in "。！？”"  # 只在句末切
        assert c.count("“") == c.count("”")  # 不在引号中间切
    lens = [len(c) for c in chunks]
    assert max(lens) - min(lens) < 250  # 大致均匀，不会剩一个小尾巴


def test_chunks_prefer_scene_and_paragraph_breaks():
    a = "陆川坐在包厢里转着酒杯。" * 40          # 480 字
    b = "那一晚之后，陆川的人设塌了。他搬出了公寓。" + "他每天去工地搬砖。" * 30
    text = a + b
    chunks = SS.split_novel_chunks(text, 600)
    assert chunks[0] == a and chunks[1].startswith("那一晚之后")  # 在场景/时间切换处切开
    para = "第一段的话。" * 50 + "\n" + "第二段的话。" * 50
    got = SS.split_novel_chunks(para, 400)
    assert got[0].endswith("第一段的话。") and got[1].startswith("第二段")


def test_split_in_half_at_sentence_near_middle():
    text = "".join(f"第{i}句叙述内容。" for i in range(100))
    a, b = SS.split_in_half(text)
    assert a + b == text and a.endswith("。") and abs(len(a) - len(b)) < 30
    assert SS.split_in_half("没有句号的一整句") == ["没有句号的一整句"]


def test_short_novel_single_chunk_and_note():
    assert SS.split_novel_chunks("短小说。", 1500) == ["短小说。"]
    assert SS.split_novel_chunks("", 1500) == []
    assert SS.chunk_note(1, 1) == ""
    note = SS.chunk_note(2, 3, {"scene": "云顶包厢", "tail": "陆川攥紧杯子"})
    assert "第 2 块" in note and "陆川攥紧杯子" in note and "结尾不要收束" in note
    assert "结尾不要收束" not in SS.chunk_note(3, 3, {"tail": "x"})


# ---------- 紧凑输出展开 ----------
def test_parse_compact_lines_and_beats():
    assert SS.parse_line("旁白：暴雨压着庭院。") == {"speaker": "旁白", "text": "暴雨压着庭院。", "kind": "narration"}
    assert SS.parse_line("赵虎：你也配站在这里？")["kind"] == "onscreen"
    assert SS.parse_line("林风（心声）：再忍一忍。") == {"speaker": "林风", "text": "再忍一忍。", "kind": "inner"}
    assert SS.parse_line("苏婉(画外)：住手！")["kind"] == "offscreen"
    assert SS.parse_line("没有说话人的一句。")["kind"] == "narration"


def test_parse_line_pseudo_speaker_falls_back_to_narration():
    """R11/P10：带冒号的叙述句不当说话人。时间提示 → 旁白（不念冒号）；角色名+动作 → 归给角色；
    别名/未提取配角 → 保留说话人（不把“王婶：…”整句塞给旁白念）。每种都记提示。"""
    names = {"陆川", "赵虎", "苏婉"}
    notes = []
    assert SS.parse_line("三年后：陆川回到了小镇。", names, notes) == \
        {"speaker": "旁白", "text": "三年后，陆川回到了小镇。", "kind": "narration"}
    assert SS.parse_line("赵虎脸色铁青：你藏了什么？", names, notes) == \
        {"speaker": "赵虎", "text": "你藏了什么？", "kind": "onscreen"}
    assert SS.parse_line("王婶：你回来啦", names, notes) == {"speaker": "王婶", "text": "你回来啦", "kind": "onscreen"}
    assert len(notes) == 3 and "三年后" in notes[0] and "赵虎脸色铁青" in notes[1] and "王婶" in notes[2]
    # 时间提示要有时间词 + 先后/方位后缀：人名不误判
    assert SS.parse_line("那天夜里：雨下大了", names)["speaker"] == "旁白"
    assert SS.parse_line("与此同时：苏婉推门", names)["speaker"] == "旁白"
    assert SS.parse_line("刘建中：快走", names)["speaker"] == "刘建中"
    assert SS.parse_line("夜无痕：哼", names)["speaker"] == "夜无痕"
    # 真角色、带标注的清单外人物、没有角色清单：照旧
    assert SS.parse_line("赵虎：你藏了什么？", names)["kind"] == "onscreen"
    assert SS.parse_line("围观族人（画外）：哄笑声", names) == {"speaker": "围观族人", "text": "哄笑声", "kind": "offscreen"}
    assert SS.parse_line("三年后：陆川回到了小镇。")["speaker"] == "三年后"
    # expand_segment 把提示挂到 parse_notes，画面人物里不出现“三年后”
    seg = SS.expand_segment({"scene": "小镇，清晨", "pos": "陆川居中", "lines": ["三年后：陆川回到了小镇。", "赵虎：站住！"],
                             "beats": ["中景|平视|陆川全身|固定|陆川推门|无|1,2"]}, names, set())
    assert [ln["kind"] for ln in seg["lines"]] == ["narration", "onscreen"] and seg["characters"] == ["赵虎", "陆川"]
    assert "三年后" not in seg["characters"] and len(seg["parse_notes"]) == 1
    # 6 段旧格式（T-211）：景别|机位|运镜|动作|表情|台词序号，没有构图和边界
    b = SS.parse_beat("中近景|过肩|固定|赵虎俯身逼近，俯视林风|冷笑，眉毛一挑|1,2")
    assert b == {"shot_size": "中近景", "camera": "过肩", "composition": "", "move": "固定",
                 "action": "赵虎俯身逼近，俯视林风", "expression": "冷笑，眉毛一挑", "boundary": "", "line_refs": [1, 2]}
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|无|")["line_refs"] == []
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|无|")["expression"] == ""  # “无”视为没有表情
    assert SS.parse_beat("特写|平视|固定|指节攥白|眼眶泛红却咬唇")["expression"] == "眼眶泛红却咬唇"  # 没写台词序号
    # 旧 5 段格式兼容：没有表情字段
    old = SS.parse_beat("中近景|过肩|固定|赵虎冷笑，俯视林风|1,2")
    assert old == {"shot_size": "中近景", "camera": "过肩", "composition": "", "move": "固定",
                   "action": "赵虎冷笑，俯视林风", "expression": "", "boundary": "", "line_refs": [1, 2]}
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|")["expression"] == ""
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕")["action"] == "扫帚柄点中手腕"
    assert SS.parse_beat({"action": "x"}) == {"action": "x"}  # 旧对象格式原样
    # 7 段新格式（T-227）：景别|机位|构图|运镜|动作|表情|台词序号
    n = SS.parse_beat("中近景|赵虎右后方，与肩同高，平视|赵虎头肩加林风肩膀，背景为廊柱|固定|赵虎俯身逼近，俯视林风|冷笑|1,2")
    assert n == {"shot_size": "中近景", "camera": "赵虎右后方，与肩同高，平视", "composition": "赵虎头肩加林风肩膀，背景为廊柱",
                 "move": "固定", "action": "赵虎俯身逼近，俯视林风", "expression": "冷笑", "boundary": "", "line_refs": [1, 2]}
    assert SS.parse_beat("特写|正对人物，与胸口齐平|头肩，背景虚化|固定|指节攥白|无|")["line_refs"] == []
    assert SS.parse_beat("特写|正对人物，与胸口齐平|头肩，背景虚化|固定|指节攥白|无|")["expression"] == ""
    # 第 8 段 = 特效边界（只在特效镜头写）；“无”视为没有
    fx = SS.parse_beat("特写|手正前方，平视|右手和戒指，背景虚化|缓慢推近|戒指泛起金光|无|2|金光只在戒指上，持续两秒，不扩散到脸")
    assert fx["boundary"] == "金光只在戒指上，持续两秒，不扩散到脸" and fx["line_refs"] == [2] and fx["composition"] == "右手和戒指，背景虚化"
    assert SS.parse_beat("特写|手正前方，平视|右手，背景虚化|固定|握拳|无|2|无")["boundary"] == ""
    # 模型在台词序号槽里写“空”“无”：当作没有台词，不能让后面的字段错位
    e = SS.parse_beat("特写|陆川左前方，与胸口齐平，平视|陆川头肩加杯沿|固定|陆川端杯的手微顿|笑意一僵|空")
    assert e["line_refs"] == [] and e["composition"] == "陆川头肩加杯沿" and e["action"] == "陆川端杯的手微顿" and e["expression"] == "笑意一僵"
    # 7 段、台词序号留空 + 有边界
    assert SS.parse_beat("特写|a|b|固定|戒指泛起金光|无||金光只在戒指上")["boundary"] == "金光只在戒指上"


def test_expand_segment_derives_fields():
    seg = SS.expand_segment(fake.FAKE_SEGMENTS_COMPACT[1], {"林风", "赵虎", "苏婉"}, {"青铜古戒"})
    assert seg["positions"].startswith("赵虎在画面左侧") and "pos" not in seg
    assert [ln["kind"] for ln in seg["lines"]] == ["onscreen", "narration", "inner", "narration"]
    assert seg["characters"][0] == "赵虎" and set(seg["characters"]) == {"赵虎", "林风", "苏婉"}
    assert seg["props"] == ["青铜古戒"]
    assert seg["tail"] == "苏婉在廊下撑伞，指尖捏紧伞柄"  # 尾态 = 最后一个小镜头的动作
    assert seg["beats"][0]["expression"] == "冷笑" and seg["beats"][1]["expression"] == ""
    assert seg["neg_prompt"] == SS.DEFAULT_NEG_PROMPT and "中近景" in seg["image_prompt"]
    assert "video_prompt" not in seg and "duration" not in seg  # 都由代码生成


def test_compact_segment_assembles_five_section_prompt():
    """精简后 video_prompt 由代码按 beats + lines + 段级字段组装，五段式完整。"""
    items = [SS.expand_segment(x, {"林风", "赵虎", "苏婉"}, {"青铜古戒"}) for x in fake.FAKE_SEGMENTS_COMPACT]
    items, _ = ST.rebalance_segments(items, FAST)
    SS.link_continuity(items)
    segs = [s for it in items for s in ST.normalize_segment(it, FAST)[0]]
    seg = segs[1]
    pic = seg["video_prompt"]
    assert pic.startswith("承接上一段：赵虎踩着积水走近") and "场景与站位：暴雨萧瑟演武场" in pic
    # 【画面】里台词只写序号（“此时赵虎说出台词①”），原文只在台词清单里出现一次
    assert "[0-" in pic and "此时赵虎说出台词①，正面或侧面露脸、口型对上" in pic and "画外音，画面人物不张嘴" in pic
    assert "你也配站在这里" not in pic
    assert "林风闭口垂眼，下颌绷紧，喉结滚动" in pic  # 小镜头的表情跟在动作后
    assert "音效：雨声，雨打油纸伞" in pic and pic.endswith("尾态：苏婉在廊下撑伞，指尖捏紧伞柄")
    assert segs[0]["video_prompt"].startswith("开场镜头") and ST.NO_SPEAKING_HINT in segs[0]["video_prompt"]
    refs = [{"type": "角色", "name": "赵虎", "path": "/x/a.png"}, {"type": "道具", "name": "青铜古戒", "path": "/x/b.png"}]
    p = assemble_video_prompt(seg, refs, seg_no=2)
    assert [ln.split("】")[0] + "】" for ln in p.split("\n")] == \
        ["【整体设定】", "【硬性参数】", "【参考素材】", "【角色参考】", "【台词清单】", "【画面】", "【硬性禁区】"]
    end = 0.5 + ST.speech_seconds("你也配站在这里？")   # 7 字 ÷ 语速（core.pacing）
    assert p.count("你也配站在这里") == 1 and f"①[0.5-{round(end, 1):g}秒·第1镜]赵虎冷笑说：你也配站在这里？" in p
    assert "[赵虎](ref1)：角色，本段主讲" in p and "[青铜古戒](ref2)：道具外观" in p
    assert "[赵虎](ref1)" in p and "[青铜古戒](ref2)" in p and "林风（心声）" not in p
    for b in seg["beats"]:  # 小镜头起止由台词时间推出
        assert 0 <= b["start"] < b["end"] <= seg["duration"]


# ---------- 逐块调用、合并、截断 ----------
class StubLLM:
    """按提示词里的小说块返回一段；块长超过 truncate_over 字时模拟截断。"""

    def __init__(self, truncate_over=10 ** 9):
        self.truncate_over = truncate_over
        self.prompts = []

    async def chat_json(self, messages, max_tokens=None, on_progress=None):
        self.max_tokens = max_tokens
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        novel = prompt.split("<<")[1].split(">>")[0]
        if len(novel) > self.truncate_over:
            raise LLMTruncatedError(30000, 16384)
        sents = [s for s in novel.split("。") if s]
        return {"segments": [{"scene": "包厢，夜", "pos": "陆川居中", "lines": [f"旁白：{s}。" for s in sents],     # 整块都拆出来（只回两句会被漏拆检查判为漏拆）
                              "beats": [f"中景|平视|固定|动作{len(self.prompts)}|1,2"]}]}


def _render(text, note):
    return f"{note}<<{text}>>"


def test_split_in_chunks_merges_and_passes_tail():
    novel = "".join(f"第{i}句叙述内容在这里写得长一点。" for i in range(150))
    llm = StubLLM()
    progress = []

    async def on_progress(i, n):  # fb4ef9a 起进度回调是 async（SSE 推送）
        progress.append((i, n))

    items, stats = run(SS.split_in_chunks(llm, novel, _render, 800, on_progress=on_progress))
    n = stats["chunks"]
    assert n == len(llm.prompts) == len(items) >= 3 and progress == [(i, n) for i in range(1, n + 1)]
    assert "上一块最后一段" in llm.prompts[1] and "动作1" in llm.prompts[1]  # 尾态传给下一块
    assert "第 1 块" in llm.prompts[0] and items[0]["tail"] == "动作1"
    assert llm.max_tokens == SS.output_tokens(SS.split_novel_chunks(novel, 800)[-1])
    SS.link_continuity(items)
    assert items[0]["continuity"] == "开场" and items[1]["continuity"] == "承接上一段：动作1"


def test_truncated_chunk_halved_then_ok():
    novel = "".join(f"第{i}句叙述内容。" for i in range(100))  # 约 800 字，一块
    llm = StubLLM(truncate_over=500)
    items, stats = run(SS.split_in_chunks(llm, novel, _render, 1500))
    assert len(llm.prompts) == 3 and len(items) == 2  # 整块截断 → 对半两块
    assert any("截断" in x for x in stats["notes"])


def test_truncated_halves_recursively_until_fits():
    """截断后递归对半切：800 字 → 400 → 200 都能装下时，切两层后成功，不报错。"""
    novel = "".join(f"第{i}句叙述内容。" for i in range(150))  # 约 1300 字，一块
    llm = StubLLM(truncate_over=400)
    items, stats = run(SS.split_in_chunks(llm, novel, _render, 2000))
    assert len(items) >= 4 and all(len(p.split("<<")[1].split(">>")[0]) for p in llm.prompts)
    assert sum("截断" in x for x in stats["notes"]) >= 2


def test_truncated_small_piece_raises_clear_error():
    """切到 MIN_HALVE_CHARS 附近还截断：多半是模型复读，报“换模型”，不无限切。"""
    novel = "".join(f"第{i}句叙述内容。" for i in range(100))  # 约 800 字
    llm = StubLLM(truncate_over=100)
    with pytest.raises(SS.ShotSplitTruncated, match="请换一个长输出稳定的模型"):
        run(SS.split_in_chunks(llm, novel, _render, 1500))
    # 整块 800 → 半块约 400（< 2×MIN_HALVE_CHARS，不再切）就报错：只调 2 次，不原样重试
    assert len(llm.prompts) == 2


def test_whole_small_chunk_truncated_keeps_original_message():
    llm = StubLLM(truncate_over=10)
    with pytest.raises(SS.ShotSplitTruncated, match="小说片段过长，模型输出被截断"):
        run(SS.split_in_chunks(llm, "林风与赵虎在演武场对峙。赵虎冷笑。", _render, 1500))


def test_budget_chunk_chars_follows_model_output_cap():
    """块大小按输出额度算：16384 tokens → 约 1600 字；8192 → 约 800 字；不超过配置上限、不低于下限。"""
    assert SS.budget_chunk_chars(16384, 4000) == int(16384 * SS.OUTPUT_BUDGET_USAGE / SS.OUTPUT_TOKENS_PER_CHAR)
    assert SS.budget_chunk_chars(8192, 4000) == int(8192 * SS.OUTPUT_BUDGET_USAGE / SS.OUTPUT_TOKENS_PER_CHAR)
    assert SS.budget_chunk_chars(16384, 1000) == 1000
    assert SS.budget_chunk_chars(16384, 4000, SS.OUTPUT_TOKENS_PER_SCRIPT_CHAR) > SS.budget_chunk_chars(16384, 4000)
    assert SS.budget_chunk_chars(0, 4000) >= SS.MIN_CHUNK_CHARS
    # 每块的预计输出不超过额度：按块上限算出来的 output_tokens 落在 16384 以内
    assert SS.output_tokens("字" * SS.budget_chunk_chars(16384, 4000)) <= 16384


def test_provider_json_output_budget():
    from core.providers.llm_provider import DoubaoLLMProvider
    zhipu = "https://open.bigmodel.cn/api/paas/v4"
    assert DoubaoLLMProvider(api_key=["k"], base_url=zhipu, model="glm-4.6-flash").json_output_budget() == 16384
    assert DoubaoLLMProvider(api_key=["k"], base_url=zhipu, model="glm-5.3-flashx").json_output_budget() == 65536 - 16384   # 5.3 系列：上限 65536，留 16384 给思考
    assert MC.max_output_tokens(zhipu, "glm-5.3-flashx") == MC.max_output_tokens(zhipu, "GLM-5.3-Flash") == 65536
    assert MC.max_output_tokens(zhipu, "glm-5.2") is None and MC.max_output_tokens("https://api.deepseek.com", "glm-5.3") is None
    assert DoubaoLLMProvider(api_key=["k"], base_url="https://api.deepseek.com/v1",
                             model="deepseek-chat").json_output_budget() == 8192


# ---------- provider：finish_reason=length 不原样重试 ----------
def _sse(chunks, finish):
    body = ""
    for i, c in enumerate(chunks):
        d = {"choices": [{"delta": {"content": c}, "finish_reason": finish if i == len(chunks) - 1 else None}]}
        body += "data: " + json.dumps(d, ensure_ascii=False) + "\n\n"
    return body + "data: [DONE]\n\n"


def _provider(handler, model="glm-4.7-flash"):
    p = DoubaoLLMProvider(api_key="k", model=model, max_retries=2)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)
    return p, Client


def test_chat_json_truncated_fails_fast(monkeypatch):
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, text=_sse(['{"segments": [', '{"scene": "x"'], "length"))
    p, Client = _provider(handler)
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}]))
    assert len(calls) == 1 and calls[0]["max_tokens"] == 16384
    # 调用方给了预期输出上限（拆分镜按块字数）：按它截断；始终思考的模型另留 4096 给思考
    p.model = "glm-4.6-flash"   # 可关思考：按调用方上限原样截断
    calls.clear()
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}], max_tokens=5000))
    assert calls[0]["max_tokens"] == 5000
    # b9af77d 起 glm-4.7 按官方口径归为始终思考（待真机验证，见 docs/prompt-opt-changelog.md R12）
    p.model = "glm-4.7-flash"
    calls.clear()
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}], max_tokens=5000))
    assert calls[0]["max_tokens"] == 9096 and calls[0]["reasoning_effort"] == "low"
    p.model = "glm-5.3-flashx"
    calls.clear()
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}], max_tokens=5000))
    assert calls[0]["max_tokens"] == 5000 + 16384 and calls[0]["reasoning_effort"] == "low" and "thinking" not in calls[0]


def test_chat_json_records_stop_and_parses(monkeypatch):
    def handler(req):
        return httpx.Response(200, text=_sse(['{"a"', ': 1}'], "stop"))
    p, Client = _provider(handler)
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    meta = {}
    text = run(p._collect_stream([{"role": "user", "content": "q"}], meta=meta))
    assert text == '{"a": 1}' and meta["finish_reason"] == "stop" and meta["chars"] == 8


# ---------- 模型能力表与思考参数兼容层 ----------
ZP = "https://open.bigmodel.cn/api/paas/v4"


def test_capability_table():
    assert MC.static_capability(ZP, "glm-4.5-flash") == MC.SWITCHABLE
    assert MC.static_capability(ZP, "glm-4.6-flash") == MC.SWITCHABLE
    # b9af77d：官方口径 GLM-4.7 / 4.5V / 5.3 系列强制思考（glm-4.7 是否真的不可关闭待真机验证，R12）
    assert MC.static_capability(ZP, "glm-4.7-flash") == MC.ALWAYS
    assert MC.static_capability(ZP, "glm-4.5v") == MC.ALWAYS
    assert MC.static_capability(ZP, "glm-5.3-flashx") == MC.ALWAYS
    assert MC.static_capability(ZP, "glm-5.2") == MC.SWITCHABLE
    assert MC.static_capability(ZP, "glm-4-flash") == MC.NONE
    gem = "https://generativelanguage.googleapis.com/v1beta/openai/"
    for url, m in ((gem, "gemini-3.8-flash"), ("https://api.deepseek.com/v1", "deepseek-chat"),
                   ("https://ark.cn-beijing.volces.com/api/v3", "doubao-seed"), ("https://x.ai/v1", "glm-5")):
        assert MC.static_capability(url, m) == MC.NONE and MC.resolve_thinking(url, m, False) == {}
    assert MC.resolve_thinking(ZP, "glm-4.6-flash", False) == {"thinking": {"type": "disabled"}}
    assert MC.resolve_thinking(ZP, "glm-4.6-flash", True) == {"thinking": {"type": "enabled"}}
    # 始终思考：实测 thinking={"type":"low"} 也回 1210，要用顶层 reasoning_effort
    assert MC.resolve_thinking(ZP, "glm-5.3-flashx", False) == {"reasoning_effort": "low"}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", False) == {"reasoning_effort": "low"}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", None) == {}
    # 手动档位优先于能力表
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", False, "high") == {"reasoning_effort": "high"}
    assert MC.resolve_thinking(gem, "gemini-3.8-flash", False, "low") == {"reasoning_effort": "low"}
    assert MC.resolve_thinking(ZP, "glm-4.6-flash", False, "disabled") == {"thinking": {"type": "disabled"}}
    assert MC.resolve_thinking(ZP, "glm-5.3-flashx", False, "auto") == {"reasoning_effort": "low"}


def _thinking_handler(seen, reject):
    def handler(req):
        body = json.loads(req.content)
        frag = {k: body[k] for k in ("thinking", "reasoning_effort") if k in body}
        seen.append(frag)
        err = reject(frag)
        if err:
            return httpx.Response(400, json={"error": err})
        return httpx.Response(200, text=_sse(['{"ok": true}'], "stop"))
    return handler


def test_always_thinking_error_switches_to_low_and_caches(monkeypatch):
    """能力表判成可关、接口却回 1210（不支持关闭思考）：自动改 low 重试，并缓存为 always。"""
    model = "glm-4.6-flash"   # 新规则下只有 4.5/4.6 与 5.x（非 5.3）是可关；4.8/4.9 一律不传思考参数
    MC.forget()
    seen = []
    always = {"code": "1210", "message": "该模型始终思考，不支持关闭思考；请使用 low、high 或 max。"}
    p, Client = _provider(_thinking_handler(seen, lambda t: always if "thinking" in t else None), model)
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    assert run(p.chat_json([{"role": "user", "content": "q"}])) == {"ok": True}
    assert seen == [{"thinking": {"type": "disabled"}}, {"reasoning_effort": "low"}]  # 400 不走退避，只为降级重试一次
    assert MC.thinking_capability(ZP, model) == MC.ALWAYS
    assert run(p.chat_json([{"role": "user", "content": "q"}])) == {"ok": True}
    assert seen[-1] == {"reasoning_effort": "low"} and len(seen) == 3  # 之后同模型直接用 low
    MC.forget()


def test_glm5_uses_low_directly(monkeypatch):
    seen = []
    p, Client = _provider(_thinking_handler(seen, lambda t: None), "glm-5.3-flashx")
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    run(p.chat_json([{"role": "user", "content": "q"}]))
    assert seen == [{"reasoning_effort": "low"}]


def test_low_also_rejected_then_dropped(monkeypatch):
    """最低档也被拒（4xx）→ 去掉思考参数再试一次，缓存为不传"""
    model = "glm-5.3-test"   # 要测的是 always 路径：新规则下 glm-5.x（非 5.3）是可关，会先试 disabled
    MC.forget()
    seen = []
    bad = {"code": "1210", "message": "该模型始终思考，不支持关闭思考"}
    p, Client = _provider(_thinking_handler(seen, lambda t: bad if t else None), model)
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    assert run(p.chat_json([{"role": "user", "content": "q"}])) == {"ok": True}
    assert seen == [{"reasoning_effort": "low"}, {}] and MC.thinking_capability(ZP, model) == MC.NONE
    MC.forget()


def test_thinking_param_unsupported_dropped_and_cached(monkeypatch):
    model = "glm-4.6-flash"
    MC.forget()
    seen = []
    bad = {"code": "1214", "message": "thinking 参数无效"}
    p, Client = _provider(_thinking_handler(seen, lambda t: bad if t else None), model)
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    assert run(p.chat_json([{"role": "user", "content": "q"}])) == {"ok": True}
    assert seen == [{"thinking": {"type": "disabled"}}, {}] and MC.thinking_capability(ZP, model) == MC.NONE
    run(p.chat_json([{"role": "user", "content": "q"}]))
    assert seen[-1] == {} and len(seen) == 3
    MC.forget()


def test_manual_thinking_mode_override(monkeypatch):
    seen = []
    p, Client = _provider(_thinking_handler(seen, lambda t: None), "glm-4.7-flash")
    p.thinking_mode = "high"
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    run(p.chat_json([{"role": "user", "content": "q"}]))
    assert seen == [{"reasoning_effort": "high"}]


def test_bad_request_reports_reason_without_retry(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": {"code": "1211", "message": "模型不存在"}})
    p, Client = _provider(handler, "glm-4.5-flash")
    monkeypatch.setattr(LP.httpx, "AsyncClient", Client)
    with pytest.raises(LLMRequestError, match="1211 模型不存在"):
        run(p.chat_json([{"role": "user", "content": "q"}]))
    assert len(calls) == 1


# ---------- 接口：长文分块、截断给出明确 4xx、进度接口 ----------
def test_split_api_long_novel_chunks_and_numbering(client, project):
    h, pid = project["user"]["headers"], project["id"]
    # 每块字数按模型输出额度算（替身默认 glm-4.5-flash：16384 tokens、关思考），SHOT_SPLIT_CHUNK_CHARS 只是上限
    novel = "".join(f"第{i}句：林风在演武场上挥着扫帚，雨越下越大。" for i in range(360))
    from config.settings import settings as _settings
    expect_chunks = len(SS.split_novel_chunks(novel, SS.budget_chunk_chars(16384, _settings.SHOT_SPLIT_CHUNK_CHARS)))
    from conftest import sse_done   # fb4ef9a 起拆分镜接口是 SSE（分块进度 + done）
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": novel}, headers=h, timeout=60)
    data = sse_done(r)["data"]
    assert data["chunks"] == expect_chunks >= 3 and data["count"] >= 6 and data["format"] == "segment"
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert [s["shot_no"] for s in shots] == list(range(1, len(shots) + 1))
    assert all(s["final_video_prompt"].count("【") >= 5 for s in shots)
    assert shots[0]["continuity"] == "开场" and shots[1]["continuity"].startswith("承接上一段")
    # 进度随 SSE 推送（fb4ef9a），轮询接口 /api/shots/split/progress 已下线


def test_split_api_truncated_returns_clear_error(client, project):
    h, pid = project["user"]["headers"], project["id"]
    novel = "林风与赵虎在演武场对峙。" + fake.TRUNCATE_MARKER + "赵虎冷笑。林风握紧扫帚。"
    from conftest import sse_events   # SSE 下模型侧错误是 error 事件，不是 4xx
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": novel}, headers=h, timeout=60)
    assert r.status_code == 200
    assert [e["message"] for e in sse_events(r) if e.get("type") == "error"] == [SS.TRUNCATED_MESSAGE]
    assert client.get("/api/shots", params={"project_id": pid}, headers=h).json() == []


def test_model_preset_thinking_mode(client, models_client):
    """设置 → 模型：预设可存思考档位，非法值按自动"""
    r = models_client.post("/api/models", json={"name": "T204 思考档位", "provider": "zhipu", "models": ["glm-5.3-flashx"],
                                         "thinking_mode": "LOW"})
    mid = r.json()["id"]
    try:
        rows = models_client.get("/api/models").json()
        row = next(x for x in rows["data"] if x["_id"] == mid)
        assert row["thinking_mode"] == "low"
        assert [m["value"] for m in rows["thinking_modes"]] == ["auto", "disabled", "low", "high"]
        models_client.put(f"/api/models/{mid}", json={**{k: v for k, v in row.items() if k != "_id"}, "thinking_mode": "max"})
        row = next(x for x in models_client.get("/api/models").json()["data"] if x["_id"] == mid)
        assert row["thinking_mode"] == "auto"
    finally:
        models_client.delete(f"/api/models/{mid}")


def test_json_bracket_repair():
    """glm-4.7-flash 实测把 ]}]} 写成 ]}}：宽松解析按括号栈纠正"""
    from core.providers.llm_provider import repair_json_brackets
    assert repair_json_brackets('{"a":[1,2}') == '{"a":[1,2]}'
    assert repair_json_brackets('{"s":[{"x":"含}括号"}}') == '{"s":[{"x":"含}括号"}]}'
    text = '{"segments":[{"lines":["旁白：一。"],"beats":["中景|平视|固定|动作|1"]}}'
    assert DoubaoLLMProvider._parse_json_lenient(text)["segments"][0]["lines"] == ["旁白：一。"]
    # glm-5.3-flashx 实测：“每段占一行”写成一行一个对象、行间漏逗号
    lines_style = '{"segments":[\n{"scene":"甲","lines":["旁白：一。"]}\n{"scene":"乙","lines":["旁白：二。" "旁白：三。"]}\n]}'
    segs = DoubaoLLMProvider._parse_json_lenient(lines_style)["segments"]
    assert [x["scene"] for x in segs] == ["甲", "乙"] and segs[1]["lines"] == ["旁白：二。", "旁白：三。"]


# ---------- 拆分镜耗时：并行、思考占满额度、漏拆 ----------
class SlowLLM(StubLLM):
    """每次调用睡一会儿，记录同时在跑的调用数。"""

    def __init__(self, delay=0.05, **kw):
        super().__init__(**kw)
        self.delay, self.running, self.peak = delay, 0, 0

    async def chat_json(self, messages, max_tokens=None, on_progress=None):
        import asyncio
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            # 第 1 块最慢：并行时它最后完成，合并顺序仍要按块序
            await asyncio.sleep(self.delay * (3 if "这是第 1 块" in messages[-1]["content"] else 1))
            if on_progress:
                await on_progress(100)
            return await super().chat_json(messages, max_tokens, None)
        finally:
            self.running -= 1


def test_parallel_chunks_keep_order_and_overlap_in_time():
    import time
    novel = "".join(f"第{i}句叙述内容在这里写得长一点。" for i in range(120))
    serial, t0 = SlowLLM(), time.monotonic()
    items_s, stats_s = asyncio.run(SS.split_in_chunks(serial, novel, _render, 500))
    t_serial = time.monotonic() - t0
    par, t0 = SlowLLM(), time.monotonic()
    progress, chars = [], []

    async def on_progress(i, n):
        progress.append((i, n))

    async def on_chars(n):
        chars.append(n)

    items_p, stats_p = asyncio.run(SS.split_in_chunks(par, novel, _render, 500, concurrency=3,
                                                       on_progress=on_progress, on_chars=on_chars))
    t_par = time.monotonic() - t0
    assert serial.peak == 1 and par.peak == 3                       # 最多 3 块同时跑
    assert stats_p["chunks"] == stats_s["chunks"] >= 4
    assert [x["lines"] for x in items_p] == [x["lines"] for x in items_s]   # 合并顺序按块序，不按完成顺序
    assert t_par < t_serial * 0.75
    assert [c["chunk"].split("/")[0] for c in stats_p["calls"]] == [str(i) for i in range(1, stats_p["chunks"] + 1)]
    assert progress[0] == (1, stats_p["chunks"]) and progress[-1][0] == stats_p["chunks"]
    assert max(chars) >= 300                                        # 并行时进度是各块已收字符的合计


def test_parallel_chunk_note_gives_previous_source_tail_instead_of_previous_result():
    novel = "".join(f"第{i}句叙述内容在这里写得长一点。" for i in range(120))
    llm = StubLLM()
    asyncio.run(SS.split_in_chunks(llm, novel, _render, 500, concurrency=4))
    second = next(p for p in llm.prompts if "这是第 2 块" in p)
    first_chunk = SS.split_novel_chunks(novel, 500)[0]
    assert "上一块原文的结尾是" in second and first_chunk[-20:] in second and "尾态是" not in second
    assert "上一块原文的结尾" not in next(p for p in llm.prompts if "这是第 1 块" in p)
    assert SS.chunk_note(1, 1) == "" and "上一块最后一段的" in SS.chunk_note(2, 3, {"scene": "包厢", "tail": "起身"}, prev_text="不该用到")


def test_parallel_failure_cancels_the_rest_and_raises():
    novel = "".join(f"第{i}句叙述内容。" for i in range(400))
    llm = StubLLM(truncate_over=50)                  # 怎么切都截断
    with pytest.raises(SS.ShotSplitTruncated):
        asyncio.run(SS.split_in_chunks(llm, novel, _render, 600, concurrency=3))


class LazyLLM(StubLLM):
    """指定的那一块前 lazy_times 次只回一句（漏拆），之后正常。"""

    def __init__(self, lazy_times):
        super().__init__()
        self.lazy_times, self.seen = lazy_times, 0

    async def chat_json(self, messages, max_tokens=None, on_progress=None):
        out = await super().chat_json(messages, max_tokens, on_progress)
        if "这是第 2 块" in messages[-1]["content"] and self.seen < self.lazy_times:
            self.seen += 1
            out["segments"][0]["lines"] = out["segments"][0]["lines"][:1]
        return out


def test_low_coverage_chunk_is_retried_once_then_reported():
    novel = "".join(f"第{i}句叙述内容在这里写得长一点。" for i in range(120))
    n = len(SS.split_novel_chunks(novel, 500))
    ok = LazyLLM(lazy_times=1)
    items, stats = asyncio.run(SS.split_in_chunks(ok, novel, _render, 500))
    assert len(ok.prompts) == n + 1 and stats["notes"] == []        # 重拆一次就好了，不提示
    assert "".join(ln["text"] for x in items for ln in x["lines"]).count("叙述内容") == 120
    assert any(c["chunk"].endswith("·重拆") for c in stats["calls"]) and min(c["coverage"] for c in stats["calls"]) < 0.5
    bad = LazyLLM(lazy_times=5)
    items, stats = asyncio.run(SS.split_in_chunks(bad, novel, _render, 500))
    assert len(bad.prompts) == n + 1                                # 只重拆一次，不无限重试
    assert any("第 2 块只拆出原文约" in x and "建议核对或重拆" in x for x in stats["notes"])
    assert len(items) == n                                          # 拆出来的那点内容仍然保留


def test_empty_output_at_token_limit_is_retried_with_full_cap(monkeypatch):
    """思考把额度吃光、正文为空（共 0 字符, finish_reason=length）：放宽到模型上限原样再试一次，不交给调用方对半切。"""
    from core.providers import llm_provider as LP
    llm = LP.DoubaoLLMProvider(api_key="k", base_url="https://open.bigmodel.cn/api/paas/v4", model="glm-5.3-flashx")
    limits = []

    async def fake_stream(messages, model, temperature=0.3, max_tokens=None, thinking=None, meta=None, on_progress=None):
        limits.append(max_tokens)
        if len(limits) == 1:
            meta["finish_reason"] = "length"
            return ""
        meta["finish_reason"] = "stop"
        return '{"segments": []}'

    monkeypatch.setattr(llm, "_collect_stream", fake_stream)
    out = asyncio.run(llm.chat_json([{"role": "user", "content": "x"}], max_tokens=8592))
    assert out == {"segments": []} and limits == [8592 + 16384, 65536]

    async def always_empty(messages, model, temperature=0.3, max_tokens=None, thinking=None, meta=None, on_progress=None):
        limits.append(max_tokens)
        meta["finish_reason"] = "length"
        return ""

    limits.clear()
    monkeypatch.setattr(llm, "_collect_stream", always_empty)
    with pytest.raises(LLMTruncatedError):
        asyncio.run(llm.chat_json([{"role": "user", "content": "x"}], max_tokens=8592))
    assert limits == [8592 + 16384, 65536]                           # 只放宽一次，第二次仍为空才报截断
