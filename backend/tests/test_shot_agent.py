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
        self.prompts.append("\n".join(m["content"] for m in messages))
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
        prompt = "\n".join(m["content"] for m in messages)
        if "你是短剧的总导演" in prompt:
            self.calls.append(("plan", prompt))
            return RAW_PLAN
        if "你是分镜的审片人" in prompt:
            self.calls.append(("review", prompt))
            return {"fixes": [{"seg": 1, "problems": ["动作太多"],
                               "beats": ["特写|正面|脸|固定|审片改过的动作|无|" + ",".join(
                                   str(i) for i in range(1, prompt.split("【分镜】")[1].split("小镜头：")[0].count("旁白：") + 1)) + "||"]}],
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
    assert all("程序检查出的问题" in p and "【原文】" in p and "【检查清单】" in p for p in review_prompts)
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


# ---------- 出图和视频提示词也读知识库和规划 ----------
def _stored_plan():
    return SA.normalize_plan(RAW_PLAN, NOVEL)


def _video_seg():
    from core.shot_timing import normalize_segment
    from core.video_models import get_video_model
    raw = SS.expand_segment({
        "scene": "暴雨青石老巷，深夜，冷蓝雨夜", "pos": "沈砚在左侧，铁面具在右侧", "mood": "肃杀",
        "lines": ["铁面具：沈探客，封家的人早就等着你了。", "旁白：沈砚低头看了一眼手中的残缺玉牌。"],
        "beats": ["中近景|铁面具左前方|头肩与提刀手臂|固定|铁面具提刀踏水向前|目光阴冷|1||沈砚背对镜头站直",
                  "特写|沈砚掌心上方|掌心与残缺玉牌|缓慢推近|拇指拂过玉牌断口|眉眼低垂|2||"]},
        {"沈砚", "铁面具"}, {"残缺玉牌", "青光长刀"})
    return dict(normalize_segment(raw, get_video_model(None))[0][0], shot_no=3)


def test_plan_lookup_per_episode_and_scene_matching():
    from core.knowledge import plan_for, plan_scene_of
    plan = _stored_plan()
    project = {"shot_plans": {"default": plan, "ep2": {"scenes": [{"name": "别的集"}]}}}
    assert plan_for(project, None) is plan and plan_for(project, "ep2")["scenes"][0]["name"] == "别的集"
    assert plan_for(project, "没有这集") is plan and plan_for({}, None) is None and plan_for({"shot_plans": "x"}) is None
    assert plan_scene_of(plan, {"scene": "暴雨青石老巷，深夜"})["no"] == 1
    assert plan_scene_of(plan, {"scene": "深夜灯火老街，雨丝斜织"})["no"] == 2
    assert plan_scene_of(plan, {"scene": "无名山洞"}) is None                       # 两场都对不上：不猜
    assert plan_scene_of({"scenes": plan["scenes"][:1]}, {"scene": "随便写的"})["no"] == 1


def test_segment_knowledge_uses_same_words_every_segment():
    from core.knowledge import knowledge_line, segment_knowledge
    plan = _stored_plan()
    seg = _video_seg()
    k = segment_knowledge(seg, CHARS, SCENES, PROPS, plan)
    assert k["axis"] == "沈砚在画面左侧面朝右，铁面具在右侧面朝左" and k["scene_name"] == "暴雨青石老巷"
    assert k["cast"] == ["铁面具：覆铁面具，只露双眼，穿黑色劲装", "沈砚：剑眉冷眼，束高马尾，穿深色短外套，左肩破口"] \
        or k["cast"] == ["沈砚：剑眉冷眼，束高马尾，穿深色短外套，左肩破口", "铁面具：覆铁面具，只露双眼，穿黑色劲装"]
    assert k["props"] == ["残缺玉牌：半块青白玉牌，刻一个模糊的封字（沈砚的）"]
    other = segment_knowledge(dict(seg, lines=[], beats=[]), CHARS, SCENES, PROPS, plan)
    assert other["cast"] == k["cast"]                                              # 同一角色各段措辞逐字相同
    assert "道具 残缺玉牌" in knowledge_line(k) and knowledge_line(None) == "" and knowledge_line({"cast": [], "props": []}) == ""
    assert segment_knowledge(seg, CHARS, SCENES, PROPS, plan, people=["沈砚"])["cast"][0].startswith("沈砚：")


def test_video_prompt_reads_plan_axis_and_character_settings():
    from core import video_prompt as VP
    from core.knowledge import segment_knowledge
    seg = _video_seg()
    plain = VP.assemble_video_prompt(seg, [])
    assert "站位约定" not in plain and "【角色与道具设定】" not in plain                # 不传知识库：和以前一样
    k = segment_knowledge(seg, CHARS, SCENES, PROPS, _stored_plan())
    p = VP.assemble_video_prompt(seg, [], knowledge=k)
    assert "站位约定（全场不变）：沈砚在画面左侧面朝右，铁面具在右侧面朝左" in p.split("\n")[0]
    assert "【角色与道具设定】" in p and "沈砚：剑眉冷眼，束高马尾，穿深色短外套，左肩破口" in p
    assert "残缺玉牌：半块青白玉牌，刻一个模糊的封字（沈砚的）" in p
    assert p.index("【整体设定】") < p.index("【角色与道具设定】") < p.index("【硬性参数】")


def test_build_upload_plan_passes_knowledge_and_stays_fine_without_plan(tmp_path):
    from core import video_prompt as VP
    from core.video_models import get_video_model
    seg = _video_seg()
    with_plan = VP.build_upload_plan(seg, CHARS, SCENES, PROPS, tmp_path, get_video_model(None), plan=_stored_plan())
    assert "站位约定（全场不变）" in with_plan["prompt"] and "【角色与道具设定】" in with_plan["prompt"]
    no_plan = VP.build_upload_plan(seg, CHARS, SCENES, PROPS, tmp_path, get_video_model(None))
    assert "站位约定" not in no_plan["prompt"] and "沈砚：剑眉冷眼" in no_plan["prompt"]   # 没规划也带角色设定
    bare = VP.build_upload_plan(seg, [], [], [], tmp_path, get_video_model(None))
    assert "【角色与道具设定】" not in bare["prompt"]                                   # 没有资产：不写空块


def test_storyboard_prompt_reads_same_axis_and_prop_ownership(tmp_path):
    from core.knowledge import segment_knowledge
    from core.storyboard import asset_sheet, panel_prompt, storyboard_panels, storyboard_prompt
    seg = _video_seg()
    k = segment_knowledge(seg, CHARS, SCENES, PROPS, _stored_plan())
    sheet = asset_sheet(seg, CHARS, SCENES, PROPS, tmp_path)
    p = storyboard_prompt("", seg, CHARS, "国漫 3D 渲染", sheet=sheet, knowledge=k)
    assert "站位约定（四格都按这个，不要左右互换）：沈砚在画面左侧面朝右，铁面具在右侧面朝左" in p
    assert "道具设定：残缺玉牌：半块青白玉牌，刻一个模糊的封字（沈砚的）" in p
    assert "【站位约定】沈砚在画面左侧" in panel_prompt(seg, storyboard_panels(seg)[0], CHARS, "国漫 3D 渲染", sheet=sheet, knowledge=k)
    assert "站位约定" not in storyboard_prompt("", seg, CHARS, "国漫 3D 渲染", sheet=sheet)


def test_plan_and_review_prompts_live_in_the_registry():
    from core.prompt_registry import build_messages, get_entry
    plan = build_messages("shot_plan", novel_text="正文在这里", asset_block="角色：沈砚", segment_seconds=15)
    assert plan[0]["role"] == "system" and "总导演" in plan[0]["content"] and "约 15 秒" in plan[0]["content"]
    assert '"plan"' in plan[0]["content"] and "【规划规则】" in plan[1]["content"]
    assert "【作品资料】\n角色：沈砚" in plan[1]["content"] and plan[1]["content"].rstrip().endswith("正文在这里")
    review = build_messages("shot_review", novel_text="原文", plan_note="知识库", review_segments="段 1")
    assert "审片人" in review[0]["content"] and '"fixes"' in review[0]["content"]
    assert "【检查清单】" in review[1]["content"] and "【分镜】\n段 1" in review[1]["content"]
    # 替身模型按提示词里的字段名判断类型：这两份提示词不能被当成拆分镜或资产提取
    for msgs in (plan, review):
        text = "\n".join(m["content"] for m in msgs)
        assert '"segments"' not in text and '"shots"' not in text and '"characters"' not in text and '"scenes"' not in text
    assert get_entry("shot_plan")["kind"] == get_entry("shot_review")["kind"] == "json"


def test_plan_contract_fields_are_understood():
    raw = {"logline": "x", "hook": "y", "plan": [dict(RAW_PLAN["scenes"][0], cast=["沈砚"], characters=None)]}
    plan = SA.normalize_plan(raw, NOVEL)
    assert plan["scenes"][0]["characters"] == ["沈砚"] and plan["scenes"][0]["name"] == "暴雨青石老巷"


# ---------- 站位约定冲突 ----------
AXIS = "沈砚在画面左侧面朝右，铁面具在右侧面朝左"


def test_sides_are_read_from_position_text_not_from_facing():
    from core.knowledge import axis_conflicts, sides_of
    names = ["沈砚", "铁面具"]
    assert sides_of(AXIS, names) == {"沈砚": "左", "铁面具": "右"}
    assert sides_of("铁面具在右侧提刀面朝左，沈砚在左侧背对镜头", names) == {"铁面具": "右", "沈砚": "左"}
    assert sides_of("沈砚面朝右站在左侧", names) == {"沈砚": "左"}
    assert sides_of("沈砚在画面中央", names) == {}
    assert axis_conflicts(AXIS, "白衣男子在左侧面朝右，沈砚在右侧持匕戒备", ["沈砚", "白衣男子"]) == \
        ["沈砚 按约定在左侧，这一段写在了右侧"]
    assert axis_conflicts(AXIS, "沈砚在左，铁面具在右", names) == [] and axis_conflicts("", "沈砚在右", names) == []


def _flipped_seg():
    seg = _seg()
    seg["positions"] = "沈砚在右侧，铁面具在左侧"
    seg["characters"] = ["沈砚", "铁面具"]
    return seg


def test_review_sees_axis_conflict_and_may_only_fix_it_towards_the_plan():
    seg = _flipped_seg()
    assert any("站位和规划的站位约定相反：沈砚 按约定在左侧" in x for x in SA.lint_segment(seg, axis=AXIS))
    assert "站位和规划的站位约定相反" in SA.segments_for_review([seg], axis=AXIS)
    good = dict(GOOD_FIX, fixes=[dict(GOOD_FIX["fixes"][0], pos="沈砚在左侧面朝右，铁面具在右侧")])
    out, _ = SA.apply_fixes([seg], good, axis=AXIS)
    assert out[0]["positions"] == "沈砚在左侧面朝右，铁面具在右侧"
    still_wrong = dict(GOOD_FIX, fixes=[dict(GOOD_FIX["fixes"][0], pos="沈砚在右侧，铁面具在左侧靠墙")])
    out, _ = SA.apply_fixes([seg], still_wrong, axis=AXIS)
    assert out[0]["positions"] == seg["positions"]                              # 改完还冲突：不采用
    fine = _seg()
    fine["characters"] = ["沈砚", "铁面具"]
    out, _ = SA.apply_fixes([fine], good, axis=AXIS)
    assert out[0]["positions"] == fine["positions"]                             # 本来没冲突：不许顺手改站位


def test_video_prompt_says_plan_wins_and_warns_when_positions_flip(tmp_path):
    from core import video_prompt as VP
    from core.video_models import get_video_model
    seg = dict(_video_seg(), positions="沈砚在右侧，铁面具在左侧")
    plan = VP.build_upload_plan(seg, CHARS, SCENES, PROPS, tmp_path, get_video_model(None), plan=_stored_plan())
    assert "下文站位与此不一致时以此为准" in plan["prompt"]
    assert any("站位和全集规划相反：沈砚 按约定在左侧" in w for w in plan["warnings"])
    ok = VP.build_upload_plan(_video_seg(), CHARS, SCENES, PROPS, tmp_path, get_video_model(None), plan=_stored_plan())
    assert "以此为准" not in ok["prompt"] and not any("站位和全集规划相反" in w for w in ok["warnings"])


# ---------- 剧本模式的规划 ----------
def test_script_chunks_map_to_plan_scenes_by_name():
    plan = _stored_plan()
    script_text = "【场次1】地点：暴雨青石老巷\n旁白：暴雨如注。\n【场次2】地点：深夜灯火老街\n旁白：他靠在墙边。"
    chunks = ["【场次1】地点：暴雨青石老巷\n旁白：暴雨如注。", "【场次2】地点：深夜灯火老街（续）\n旁白：他靠在墙边。"]
    assert [s["no"] for s in SA.scenes_of_chunk(plan, script_text, chunks, 2)] == [2]
    note = SA.plan_note(plan, script_text, chunks, 2)
    assert "场景名统一写“深夜灯火老街”" in note and "本块之前已经发生：沈砚被围杀后反杀" in note
    assert SA.axis_of_chunk(plan, script_text, chunks, 1).startswith("沈砚在画面左侧")
    unknown = ["【场次3】地点：无名山洞\n旁白：洞里很黑。"]
    assert len(SA.scenes_of_chunk(plan, script_text, unknown, 1)) == 2 and SA.axis_of_chunk(plan, script_text, unknown, 1) == ""
    assert "本块之前已经发生" not in SA.plan_note(plan, script_text, unknown, 1)   # 认不出是哪一场：不编前情


# ---------- 审片补漏拍 ----------
SOURCE = "刀锋贴着沈砚的耳畔划过。他反手将短匕刺入了对方要害。黑衣人捂着颈侧倒下。白衣男子问：“这就是你要找的？”巷子恢复了平静。"


def _missing(**kw):
    m = {"what": "白衣男子的问话没拍", "after": 1, "lines": ["白衣男子：这就是你要找的？"],
         "beats": ["近景|正面平视|白衣男子头肩|固定|白衣男子垂眼看向地上的人|眉梢微挑|1||"]}
    m.update(kw)
    return m


def test_review_adds_segment_for_missed_plot_when_lines_are_verbatim():
    out, notes = SA.apply_fixes([_seg()], {"fixes": [], "missing": [_missing()]}, source=SOURCE,
                                char_names={"沈砚", "白衣男子"})
    assert len(out) == 2 and out[1]["lines"][0]["speaker"] == "白衣男子" and out[1]["lines"][0]["text"] == "这就是你要找的？"
    assert out[1]["scene"] == "暴雨青石老巷，深夜" and out[1]["positions"] == "沈砚在左，铁面具在右"   # 场景站位沿用前一段
    assert out[1]["characters"] == ["白衣男子"] and out[1]["beats"][0]["line_refs"] == [1]
    assert out[1]["reviewed"] == ["审片补的段：白衣男子的问话没拍"]
    assert notes == ["审片补了 1 段漏拍的情节：白衣男子的问话没拍"]


def test_review_only_reports_when_added_segment_is_not_safe():
    cases = [
        _missing(lines=["白衣男子：你终于来了。"]),                              # 原文里没有这句：不许编台词
        _missing(lines=["旁白：刀锋贴着沈砚的耳畔划过。"]),                      # 已经有段念过：不算漏
        _missing(lines=[]),                                                      # 没有可念的原话：由人来补
        _missing(beats=["近景|正面平视|头肩|固定||无|1||"]),                     # 小镜头没写动作
        _missing(beats=["近景|正面平视|头肩|固定|垂眼|无|||"]),                  # 台词没被引用
        _missing(after=7),                                                       # 段号不存在
        "收尾画面没拍",                                                          # 旧格式：只有一句话
    ]
    for m in cases:
        out, notes = SA.apply_fixes([_seg()], {"fixes": [], "missing": [m]}, source=SOURCE)
        assert len(out) == 1 and len(notes) == 1 and notes[0].startswith("审片发现原文里有、分镜没拍到的情节："), m
    # 不传原文（老调用方式）也只提示
    out, notes = SA.apply_fixes([_seg()], {"fixes": [], "missing": [_missing()]})
    assert len(out) == 1 and "没拍到的情节" in notes[0]


def test_review_additions_keep_order_and_fix_numbers_still_point_at_original_segments():
    a, b = _seg(), SS.expand_segment({"scene": "街口", "pos": "沈砚在左", "mood": "余悸",
                                      "lines": ["旁白：巷子恢复了平静。"], "beats": ["全景|高处|整条巷子|固定|雨水冲走血迹|无|1"]})
    raw = {"fixes": [dict(GOOD_FIX["fixes"][0], seg=5)],
           "missing": [_missing(after=5, what="问话"),
                       _missing(after=5, what="倒下", lines=["旁白：黑衣人捂着颈侧倒下。"],
                                beats=["中景|侧面|黑衣人全身|固定|黑衣人捂着颈侧跪倒|无|1||"]),
                       _missing(after=0, what="放最前", lines=["旁白：白衣男子问。"], beats=["近景|正面|头肩|固定|抬眼|无|1||"])]}
    out, notes = SA.apply_fixes([a, b], raw, first_index=5, source=SOURCE)
    texts = [seg["lines"][0]["text"] for seg in out]
    assert texts == ["白衣男子问。", "刀锋贴着沈砚的耳畔划过。", "这就是你要找的？", "黑衣人捂着颈侧倒下。", "巷子恢复了平静。"]
    assert [x["action"] for x in out[1]["beats"]] == ["刀锋贴耳掠过", "沈砚反手刺出短匕"]     # 修改仍落在原来的第 5 段
    assert notes == ["审片改了 1 段的小镜头", "审片补了 3 段漏拍的情节：问话；倒下；放最前"]
