"""分镜智能体（core/shot_agent）：先规划、再拆、拆完审；以及三步共用的作品知识库（core/knowledge）。"""
import asyncio

from core import shot_agent as SA
from core import shot_split as SS
from core.knowledge import build_relations, knowledge_text
from core.providers.llm_provider import LLMTruncatedError

NOVEL = ("暴雨如注，冲刷着青石板。刀锋贴着沈砚的耳畔划过。他反手将短匕刺入了对方要害。黑衣人倒下。" * 6
         + "沈砚走出了巷子，来到了一条街道上。他靠在墙边，大口喘气。他掏出一颗药丸吞了下去。" * 6)
STREET_AT = NOVEL.index("沈砚走出了巷子")
RAW_PLAN = {"logline": "沈砚雨夜突围", "hook": "刀锋贴着耳畔划过，睫毛一颤",
            "scenes": [
                {"no": 1, "name": "暴雨青石老巷", "time": "深夜", "characters": ["沈砚", "铁面具"],
                 "axis": "沈砚在画面左侧面朝右，铁面具在右侧面朝左", "summary": "沈砚被围杀后反杀", "start": "暴雨如注，冲刷着青石板"},
                {"no": 2, "name": "深夜灯火老街", "time": "深夜", "characters": ["沈砚"],
                 "axis": "沈砚在左侧倚墙面朝右", "summary": "沈砚负伤服药", "start": "沈砚走出了 巷子，来到了一条街"}]}


def run(coro):
    return asyncio.run(coro)


# ---------- 规划 ----------
def test_normalize_plan_locates_scene_starts_ignoring_whitespace():
    plan = SA.normalize_plan(RAW_PLAN, NOVEL)
    assert [s["name"] for s in plan["scenes"]] == ["暴雨青石老巷", "深夜灯火老街"]
    assert plan["scenes"][0]["offset"] == 0 and plan["scenes"][1]["offset"] == STREET_AT
    assert plan["hook"].startswith("刀锋") and plan["scenes"][0]["axis"].startswith("沈砚在画面左侧")


def test_normalize_plan_rejects_wrong_shapes_and_survives_bad_anchor():
    assert SA.normalize_plan({"scenes": "x"}, NOVEL) is None and SA.normalize_plan([], NOVEL) is None
    assert SA.normalize_plan({"scenes": [{"name": "老巷", "description": "资产格式，不是规划"}]}, NOVEL) is None
    raw = {"scenes": [dict(RAW_PLAN["scenes"][0]), dict(RAW_PLAN["scenes"][1], start="原文里根本没有这句话")]}
    plan = SA.normalize_plan(raw, NOVEL)
    assert plan["scenes"][1]["offset"] is None and plan["scenes"][1]["name"] == "深夜灯火老街"   # 定位不到也保留设定


def test_plan_chunks_cut_at_scene_boundary_and_cover_whole_text():
    plan = SA.normalize_plan(RAW_PLAN, NOVEL)
    chunks = SA.plan_chunks(plan, NOVEL, 200)
    assert "".join(chunks) == NOVEL and all(len(c) <= 200 for c in chunks)
    assert any(c.startswith("沈砚走出了巷子") for c in chunks)                   # 场与场之间一定断开
    assert SA.plan_chunks(None, NOVEL, 200) is None
    one_scene = SA.normalize_plan({"scenes": RAW_PLAN["scenes"][:1]}, NOVEL)
    assert SA.plan_chunks(one_scene, NOVEL, 200) is None                         # 只有一场：用缺省分块


def test_plan_note_tells_each_chunk_its_scene_axis_and_prior_events():
    plan = SA.normalize_plan(RAW_PLAN, NOVEL)
    chunks = SA.plan_chunks(plan, NOVEL, 200)
    first = SA.plan_note(plan, NOVEL, chunks, 1)
    assert "全集第一段的第一个小镜头用这个画面开场：刀锋贴着耳畔划过" in first
    assert "场景名统一写“暴雨青石老巷”" in first and "铁面具在右侧面朝左" in first and "本块之前已经发生" not in first
    last = SA.plan_note(plan, NOVEL, chunks, len(chunks))
    assert "场景名统一写“深夜灯火老街”" in last and "本块之前已经发生：沈砚被围杀后反杀" in last
    assert "开场" not in last.split("本块之前")[1] and "铁面具在右侧" not in last   # 不是这一场的站位不写
    assert SA.plan_note(None, NOVEL, chunks, 1) == ""


class PlanLLM:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    async def chat_json(self, messages, max_tokens=None, on_progress=None):
        self.prompts.append(messages[-1]["content"])
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_make_plan_success_and_graceful_failures():
    plan, msg = run(SA.make_plan(PlanLLM(RAW_PLAN), NOVEL, "角色：沈砚"))
    assert len(plan["scenes"]) == 2 and msg == "全集规划：2 场（暴雨青石老巷、深夜灯火老街）"
    for bad in (LLMTruncatedError(0, 100), RuntimeError("网络断了"), {"segments": []}, {"scenes": []}):
        plan, msg = run(SA.make_plan(PlanLLM(bad), NOVEL))
        assert plan is None and "按分块各自拆" in msg                              # 规划失败不影响后面照常拆


# ---------- 审片 ----------
def _seg():
    return SS.expand_segment({
        "scene": "暴雨青石老巷，深夜", "pos": "沈砚在左，铁面具在右", "mood": "肃杀",
        "lines": ["旁白：刀锋贴着沈砚的耳畔划过。", "旁白：他反手将短匕刺入了对方要害。"],
        "beats": ["特写|沈砚左侧|侧脸与刀锋|固定|沈砚旋身，拔匕，前冲，反手刺出，收势|瞳孔一缩|1,2"]})


def test_lint_finds_what_code_can_see():
    issues = SA.lint_segment(_seg(), first=False)
    assert any("只有 1 个小镜头" in x for x in issues) and any("动作有 5 个分句" in x for x in issues)
    far = SS.expand_segment({"lines": ["旁白：暴雨如注。"], "beats": ["远景|高处俯拍|整条雨巷|固定|雨落长巷|无|1"]})
    assert any("全集第一段" in x for x in SA.lint_segment(far, first=True)) and not SA.lint_segment(far, first=False)
    lost = SS.expand_segment({"lines": ["旁白：甲。", "旁白：乙。"],
                              "beats": ["近景|正面|头肩|固定|抬头|无|1", "特写|侧面|手|固定|握拳|无|"]})
    assert any("台词 2 没有挂在任何小镜头上" in x for x in SA.lint_segment(lost))


def test_segments_for_review_shows_lines_beats_and_code_findings():
    text = SA.segments_for_review([_seg()], first_index=1, opening=True)
    assert "段 1｜场景：暴雨青石老巷，深夜｜站位：沈砚在左，铁面具在右" in text
    assert "1. 旁白：刀锋贴着沈砚的耳畔划过。" in text
    assert "特写|沈砚左侧|侧脸与刀锋|固定|沈砚旋身，拔匕，前冲，反手刺出，收势|瞳孔一缩|1,2||" in text
    assert "程序检查出的问题：" in text and "只留 1 个主动作" in text


GOOD_FIX = {"fixes": [{"seg": 1, "problems": ["一个镜头塞了五个动作"],
                       "beats": ["特写|沈砚左侧|侧脸与刀锋|固定|刀锋贴耳掠过|睫毛微颤|1||",
                                 "近景|两人侧面|沈砚反手与黑衣人|快速跟拍|沈砚反手刺出短匕|咬肌绷紧|2||黑衣人松开刀柄"]}],
            "missing": ["黑衣人倒下没有拍"]}


def test_apply_fixes_replaces_beats_but_never_touches_lines():
    seg = _seg()
    out, notes = SA.apply_fixes([seg], GOOD_FIX)
    assert [b["action"] for b in out[0]["beats"]] == ["刀锋贴耳掠过", "沈砚反手刺出短匕"]
    assert out[0]["beats"][1]["others"] == "黑衣人松开刀柄" and out[0]["tail"] == "沈砚反手刺出短匕"
    assert out[0]["lines"] == seg["lines"] and "video_prompt" not in out[0]
    assert out[0]["reviewed"] == ["一个镜头塞了五个动作"]
    assert notes == ["审片改了 1 段的小镜头", "审片发现原文里有、分镜没拍到的情节：黑衣人倒下没有拍"]
    assert len(seg["beats"]) == 1                                                  # 原对象不被改动


def test_apply_fixes_rejects_unsafe_changes():
    seg = _seg()
    bad_cases = [
        {"fixes": [{"seg": 9, "beats": GOOD_FIX["fixes"][0]["beats"]}]},                       # 段号不存在
        {"fixes": [{"seg": 1, "beats": []}]},                                                  # 没有小镜头
        {"fixes": [{"seg": 1, "beats": ["特写|侧面|脸|固定|抬头|无|1||"]}]},                      # 台词 2 没人引用
        {"fixes": [{"seg": 1, "beats": ["特写|侧面|脸|固定|抬头|无|1,2,5||"]}]},                  # 台词序号越界
        {"fixes": [{"seg": 1, "beats": ["特写|侧面|脸|固定|抬头|无|1,2||"] * 9}]},                # 太多
        {"fixes": [{"seg": 1, "lines": ["旁白：改台词"], "beats": "不是列表"}]},
        {"fixes": "x"}, "不是对象", None,
    ]
    for raw in bad_cases:
        out, notes = SA.apply_fixes([seg], raw)
        assert out[0]["beats"] == seg["beats"] and not any("改了" in n for n in notes), raw


def test_review_chunk_degrades_when_model_fails_or_format_is_legacy():
    seg = _seg()
    out, notes = run(SA.review_chunk(PlanLLM(RuntimeError("boom")), "原文", [seg]))
    assert out == [seg] and notes == ["有一块的审片没有成功（模型调用失败），这部分保留拆分的原始结果"]
    legacy = [{"text": "旧格式镜头", "prompt": "x"}]
    llm = PlanLLM(GOOD_FIX)
    assert run(SA.review_chunk(llm, "原文", legacy)) == (legacy, []) and llm.prompts == []      # 旧格式不审
    out, notes = run(SA.review_chunk(PlanLLM({}), "原文", [seg]))
    assert out[0]["beats"] == seg["beats"] and notes == []                                      # 没问题：原样


def test_summarize_notes_adds_up_changed_counts():
    assert SA.summarize_notes(["审片改了 2 段的小镜头", "审片改了 1 段的小镜头", "x", "x"]) == ["审片改了 3 段的小镜头", "x"]
    assert SA.summarize_notes([]) == []


# ---------- 三步串起来 ----------
class AgentLLM:
    """按提示词类型分别回答规划、拆分、审片，并记录每种调用。"""

    def __init__(self):
        self.calls = []

    async def chat_json(self, messages, max_tokens=None, on_progress=None):
        prompt = messages[-1]["content"]
        if "你是短剧的总导演" in prompt:
            self.calls.append(("plan", prompt))
            return RAW_PLAN
        if "你是分镜的审片人" in prompt:
            self.calls.append(("review", prompt))
            return {"fixes": [{"seg": 1, "problems": ["动作太多"],
                               "beats": ["特写|正面|脸|固定|审片改过的动作|无|" + ",".join(
                                   str(i) for i in range(1, prompt.split("小镜头：")[0].count("旁白：") + 1)) + "||"]}],
                    "missing": []}
        self.calls.append(("split", prompt))
        novel = prompt.split("<<")[1].split(">>")[0]
        sents = [s for s in novel.split("。") if s]
        return {"segments": [{"scene": "x", "pos": "y", "lines": [f"旁白：{s}。" for s in sents],
                              "beats": ["中景|平视|全身|固定|拆出来的动作一，动作二，动作三，动作四|无|" + ",".join(
                                  str(i) for i in range(1, len(sents) + 1))]}]}


def test_plan_then_split_then_review_pipeline():
    llm = AgentLLM()
    plan, _ = run(SA.make_plan(llm, NOVEL))
    chunks = SA.plan_chunks(plan, NOVEL, 300)

    async def reviewer(text, segs, index, opening):
        return await SA.review_chunk(llm, text, segs, SA.plan_note(plan, NOVEL, chunks, index), opening=opening)

    items, stats = run(SS.split_in_chunks(
        llm, NOVEL, lambda text, note: f"{note}<<{text}>>", 300, chunks=chunks, concurrency=3,
        note_extra=lambda i: SA.plan_note(plan, NOVEL, chunks, i), reviewer=reviewer))
    kinds = [k for k, _ in llm.calls]
    assert kinds.count("plan") == 1 and kinds.count("split") == kinds.count("review") == len(chunks) >= 2
    split_prompts = [p for k, p in llm.calls if k == "split"]
    assert all("【全集规划】" in p for p in split_prompts)                            # 每块都带着同一份规划
    assert sum("全集第一段的第一个小镜头用这个画面开场" in p for p in split_prompts) == 1
    review_prompts = [p for k, p in llm.calls if k == "review"]
    assert all("程序检查出的问题" in p and "【小说原文】" in p for p in review_prompts)
    assert all(x["beats"][0]["action"] == "审片改过的动作" for x in items)             # 审片的修改生效
    assert "".join(ln["text"] for x in items for ln in x["lines"]) == NOVEL          # 台词一个字没丢、顺序没乱
    assert SA.summarize_notes(stats["review_notes"]) == [f"审片改了 {len(chunks)} 段的小镜头"]


# ---------- 知识库 ----------
CHARS = [{"name": "沈砚", "gender": "male", "age_group": "青年", "importance": "main", "face": "剑眉冷眼，束高马尾",
          "forms": [{"name": "雨夜负伤", "outfit": "深色短外套，左肩破口", "scene_nos": [1]},
                    {"name": "常服", "outfit": "青色长衫，腰间挂残缺玉牌", "scene_nos": [2]}]},
         {"name": "铁面具", "importance": "support", "face": "覆铁面具，只露双眼", "forms": [{"name": "领队", "outfit": "黑色劲装"}]}]
SCENES = [{"name": "暴雨青石老巷", "description": "狭长的青石板老巷，两侧高墙，积水反光"}]
PROPS = [{"name": "残缺玉牌", "description": "半块青白玉牌，刻一个模糊的封字"},
         {"name": "青光长刀", "description": "铁面具的佩刀，刀身泛青光"}]


def test_relations_link_props_scenes_and_characters():
    plan = SA.normalize_plan(RAW_PLAN, NOVEL)
    rel = build_relations(CHARS, SCENES, PROPS, plan)
    assert rel["prop_owners"] == {"残缺玉牌": ["沈砚"], "青光长刀": ["铁面具"]}       # 一个从角色穿搭里认，一个从道具描述里认
    assert rel["char_props"] == {"沈砚": ["残缺玉牌"], "铁面具": ["青光长刀"]}
    assert rel["scene_cast"] == {"暴雨青石老巷": ["沈砚", "铁面具"]}                   # 来自全集规划


def test_knowledge_text_is_one_linked_document_and_bounded():
    plan = SA.normalize_plan(RAW_PLAN, NOVEL)
    kb = knowledge_text(CHARS, SCENES, PROPS, plan)
    assert kb.startswith("【作品知识库】")
    assert "- 沈砚（主角，男，青年）；长相：剑眉冷眼，束高马尾" in kb
    assert "形态「雨夜负伤」穿：深色短外套，左肩破口（第 1 场）" in kb and "相关道具：残缺玉牌" in kb
    assert "- 暴雨青石老巷；狭长的青石板老巷，两侧高墙，积水反光；在这里出场：沈砚、铁面具" in kb
    assert "- 青光长刀；铁面具的佩刀，刀身泛青光；相关角色：铁面具" in kb
    assert knowledge_text([], [], []) == ""
    many = [{"name": f"角色{i}", "face": "很长的长相描述" * 20, "forms": [{"outfit": "很长的穿搭" * 20}]} for i in range(60)]
    assert len(knowledge_text(many, [], [], limit=1200)) <= 1200
