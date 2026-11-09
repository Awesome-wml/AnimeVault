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
    # 6 段格式（T-211）：景别|机位|运镜|动作|表情|台词序号
    b = SS.parse_beat("中近景|过肩|固定|赵虎俯身逼近，俯视林风|冷笑，眉毛一挑|1,2")
    assert b == {"shot_size": "中近景", "camera": "过肩", "move": "固定", "action": "赵虎俯身逼近，俯视林风",
                 "expression": "冷笑，眉毛一挑", "line_refs": [1, 2]}
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|无|")["line_refs"] == []
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|无|")["expression"] == ""  # “无”视为没有表情
    assert SS.parse_beat("特写|平视|固定|指节攥白|眼眶泛红却咬唇")["expression"] == "眼眶泛红却咬唇"  # 没写台词序号
    # 旧 5 段格式兼容：没有表情字段
    old = SS.parse_beat("中近景|过肩|固定|赵虎冷笑，俯视林风|1,2")
    assert old == {"shot_size": "中近景", "camera": "过肩", "move": "固定", "action": "赵虎冷笑，俯视林风",
                   "expression": "", "line_refs": [1, 2]}
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕|")["expression"] == ""
    assert SS.parse_beat("特写|平视|慢动作|扫帚柄点中手腕")["action"] == "扫帚柄点中手腕"
    assert SS.parse_beat({"action": "x"}) == {"action": "x"}  # 旧对象格式原样


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
    # 画内台词写成“人物+表情说：台词”，表情来自该小镜头；台词原文不动
    assert "[0-" in pic and "赵虎冷笑说：你也配站在这里？（正面露脸，口型对上）" in pic and "画外音，画面人物不张嘴" in pic
    assert "林风闭口垂眼，下颌绷紧，喉结滚动" in pic  # 小镜头的表情跟在动作后
    assert "音效：雨声，雨打油纸伞" in pic and pic.endswith("尾态：苏婉在廊下撑伞，指尖捏紧伞柄")
    assert segs[0]["video_prompt"].startswith("开场镜头") and ST.NO_SPEAKING_HINT in segs[0]["video_prompt"]
    refs = [{"type": "角色", "name": "赵虎", "path": "/x/a.png"}, {"type": "道具", "name": "青铜古戒", "path": "/x/b.png"}]
    p = assemble_video_prompt(seg, refs, seg_no=2)
    assert [ln.split("】")[0] + "】" for ln in p.split("\n")] == \
        ["【整体设定】", "【硬性参数】", "【参考素材】", "【画面】", "【台词与旁白】", "【硬性禁区】"]
    assert "赵虎【@图片1】" in p and "青铜古戒【@图片2】" in p and "林风（心声）" not in p
    for b in seg["beats"]:  # 小镜头起止由台词时间推出
        assert 0 <= b["start"] < b["end"] <= seg["duration"]


# ---------- 逐块调用、合并、截断 ----------
class StubLLM:
    """按提示词里的小说块返回一段；块长超过 truncate_over 字时模拟截断。"""

    def __init__(self, truncate_over=10 ** 9):
        self.truncate_over = truncate_over
        self.prompts = []

    async def chat_json(self, messages, max_tokens=None):
        self.max_tokens = max_tokens
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        novel = prompt.split("<<")[1].split(">>")[0]
        if len(novel) > self.truncate_over:
            raise LLMTruncatedError(30000, 16384)
        sents = [s for s in novel.split("。") if s]
        return {"segments": [{"scene": "包厢，夜", "pos": "陆川居中", "lines": [f"旁白：{s}。" for s in sents[:2]],
                              "beats": [f"中景|平视|固定|动作{len(self.prompts)}|1,2"]}]}


def _render(text, note):
    return f"{note}<<{text}>>"


def test_split_in_chunks_merges_and_passes_tail():
    novel = "".join(f"第{i}句叙述内容在这里写得长一点。" for i in range(150))
    llm = StubLLM()
    progress = []
    items, stats = run(SS.split_in_chunks(llm, novel, _render, 800, on_progress=lambda i, n: progress.append((i, n))))
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


def test_truncated_twice_raises_clear_error():
    novel = "".join(f"第{i}句叙述内容。" for i in range(100))
    llm = StubLLM(truncate_over=100)
    with pytest.raises(SS.ShotSplitTruncated, match="小说片段过长，模型输出被截断"):
        run(SS.split_in_chunks(llm, novel, _render, 1500))
    assert len(llm.prompts) == 2  # 整块 1 次 + 第一个半块 1 次，不原样重试


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
    calls.clear()
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}], max_tokens=5000))
    assert calls[0]["max_tokens"] == 5000
    p.model = "glm-5.3-flashx"
    calls.clear()
    with pytest.raises(LLMTruncatedError):
        run(p.chat_json([{"role": "user", "content": "q"}], max_tokens=5000))
    assert calls[0]["max_tokens"] == 9096 and calls[0]["reasoning_effort"] == "low" and "thinking" not in calls[0]


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
    assert MC.static_capability(ZP, "glm-4.7-flash") == MC.SWITCHABLE
    assert MC.static_capability(ZP, "glm-5.3-flashx") == MC.ALWAYS
    assert MC.static_capability(ZP, "glm-4-flash") == MC.NONE
    gem = "https://generativelanguage.googleapis.com/v1beta/openai/"
    for url, m in ((gem, "gemini-3.8-flash"), ("https://api.deepseek.com/v1", "deepseek-chat"),
                   ("https://ark.cn-beijing.volces.com/api/v3", "doubao-seed"), ("https://x.ai/v1", "glm-5")):
        assert MC.static_capability(url, m) == MC.NONE and MC.resolve_thinking(url, m, False) == {}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", False) == {"thinking": {"type": "disabled"}}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", True) == {"thinking": {"type": "enabled"}}
    # 始终思考：实测 thinking={"type":"low"} 也回 1210，要用顶层 reasoning_effort
    assert MC.resolve_thinking(ZP, "glm-5.3-flashx", False) == {"reasoning_effort": "low"}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", None) == {}
    # 手动档位优先于能力表
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", False, "high") == {"reasoning_effort": "high"}
    assert MC.resolve_thinking(gem, "gemini-3.8-flash", False, "low") == {"reasoning_effort": "low"}
    assert MC.resolve_thinking(ZP, "glm-4.7-flash", False, "disabled") == {"thinking": {"type": "disabled"}}
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
    model = "glm-4.9-flash"
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
    model = "glm-5.9-test"
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
    novel = "".join(f"第{i}句：林风在演武场上挥着扫帚，雨越下越大。" for i in range(150))  # 约 3500 字 → 3 块
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": novel}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["chunks"] == 3 and data["count"] >= 6 and data["format"] == "segment"
    shots = client.get("/api/shots", params={"project_id": pid}, headers=h).json()
    assert [s["shot_no"] for s in shots] == list(range(1, len(shots) + 1))
    assert all(s["final_video_prompt"].count("【") >= 5 for s in shots)
    assert shots[0]["continuity"] == "开场" and shots[1]["continuity"].startswith("承接上一段")
    # 拆完进度清空
    assert client.get("/api/shots/split/progress", params={"project_id": pid}, headers=h).json()["data"] is None


def test_split_api_truncated_returns_clear_error(client, project):
    h, pid = project["user"]["headers"], project["id"]
    novel = "林风与赵虎在演武场对峙。" + fake.TRUNCATE_MARKER + "赵虎冷笑。林风握紧扫帚。"
    r = client.post("/api/shots/split", json={"project_id": pid, "novel_paragraph": novel}, headers=h, timeout=60)
    assert r.status_code == 422 and r.json()["detail"] == SS.TRUNCATED_MESSAGE
    assert client.get("/api/shots", params={"project_id": pid}, headers=h).json() == []


def test_model_preset_thinking_mode(client):
    """设置 → 模型：预设可存思考档位，非法值按自动"""
    r = client.post("/api/models", json={"name": "T204 思考档位", "provider": "zhipu", "models": ["glm-5.3-flashx"],
                                         "thinking_mode": "LOW"})
    mid = r.json()["id"]
    try:
        rows = client.get("/api/models").json()
        row = next(x for x in rows["data"] if x["_id"] == mid)
        assert row["thinking_mode"] == "low"
        assert [m["value"] for m in rows["thinking_modes"]] == ["auto", "disabled", "low", "high"]
        client.put(f"/api/models/{mid}", json={**{k: v for k, v in row.items() if k != "_id"}, "thinking_mode": "max"})
        row = next(x for x in client.get("/api/models").json()["data"] if x["_id"] == mid)
        assert row["thinking_mode"] == "auto"
    finally:
        client.delete(f"/api/models/{mid}")


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
