"""分镜智能体：先规划、再拆、拆完审。

原来拆分镜是“一份提示词、每块调用一次”：模型只看得到自己这一块，没有全篇视角，拆完也没人复查，
穿帮（一镜四个动作、昏迷的人在理衣袖、左右站位来回换）只能靠事后一条条写代码规则去补。
这里把它拆成三步，每一步是一次独立的模型调用，各司其职：

1. 规划（make_plan）：通读全文，只定大局——这一集分几场、每场在哪、谁出场、左右站位怎么约定、
   每场讲了什么、开场用哪个画面抓人。不拆镜头。
2. 拆分（core.shot_split.split_in_chunks）：按规划的场次边界分块，每块都带着同一份规划去拆，
   场景名、站位、前情各块一致。
3. 审片（review_chunk）：把原文、拆出来的段、代码检查出的问题一起交给模型，对照清单逐段检查，
   只返回需要改的段的新小镜头。台词一个字不许动。

任何一步失败（模型报错、返回结构不对、改坏了）都退回上一步的结果，不让拆分整体失败。
规划与审片的提示词写在本文件，不走提示词注册表（暂不支持用户自定义）。
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from core.shot_split import _drop_hollow_beats, parse_beat, split_novel_chunks

logger = logging.getLogger(__name__)

PLAN_MAX_TOKENS = 4096           # 规划的输出很短：几场戏的清单
MAX_PLAN_SCENES = 12
MIN_ANCHOR_CHARS = 6             # 场次起点的原文摘录至少这么长才拿去定位（太短会撞到别处）
REVIEW_TOKENS_PER_CHAR = 5       # 审片输出按原文字数估：只回要改的段，比拆分少
MIN_REVIEW_TOKENS = 3000
MAX_BEATS_PER_SEGMENT = 6        # 审片给的新小镜头超过这个数不采用
MAX_ACTION_CLAUSES = 3

PLAN_PROMPT = """你是短剧的总导演。下面是一集的小说全文。请通读全文，只做整体规划，不要拆镜头、不要改写原文。

{asset_block}

每个视频段固定约 {segment_seconds} 秒，后面会有人按你的规划逐块拆成视频段，所以你定的东西要让各块保持一致。

请输出一个 JSON 对象：
{{"logline": "一句话说清这一集讲了什么（30 字内）",
 "hook": "开场 3 秒用哪个画面抓人：从原文开头部分挑一个最有冲击力的瞬间，写成看得见的动作（30 字内）",
 "scenes": [
   {{"no": 1,
     "name": "场景名。已有资产清单里有对应场景就原样用那个名字，没有再自己起（8 字内，不带时辰）",
     "time": "时辰，如 深夜、黄昏",
     "characters": ["这一场出场的角色，用资产清单里的名字"],
     "axis": "站位约定：谁在画面左侧、谁在右侧、各自面朝哪边。同一场里固定不变（40 字内）",
     "summary": "这一场发生了什么（50 字内）",
     "start": "这一场在原文里开头的 10 到 16 个字，必须逐字照抄原文，不要改一个字"}}
 ]}}

规则：
- 按地点或时间的变化划分场次。同一地点连续发生的戏算一场，不要拆碎；三千字的一集一般是 1 到 4 场。
- 第一场的 start 必须是全文最开头的那几个字。场次按原文先后顺序排列。
- 只写原文里有的内容，不要补写情节。

【小说全文】
{novel}
"""

REVIEW_PROMPT = """你是分镜的审片人。下面有三样东西：一段小说原文、按它拆出来的分镜、程序自动检查出的问题。
请对照原文逐段检查分镜，找出会让成片穿帮的地方，并给出改好的小镜头。
人物的长相穿着、场景的样子、谁拿着什么道具，以下面的知识库和规划为准；分镜里和它矛盾的地方也要改。

{plan_note}

【检查清单】
1. 一个小镜头只能有 1 个主动作（“原本怎样 → 发生什么 → 停在什么姿态”）。把转身、冲刺、拔刀、落泪堆在一起的要拆成几个小镜头或删到只剩一个。
2. 人物状态前后要对得上：已经倒地、昏迷的人不能再有站着的动作；已经脱手的兵器不能还握在手里；受伤的部位前后一致。
3. 画面要拍到台词说的事：旁白讲“刀锋贴着耳畔划过”，对应的小镜头里就要有这个画面；不能台词说一件事、画面拍另一件事。
4. 画内对白（有人张嘴说话）所在的小镜头，镜头要对着说话的人。
5. 没出场的人不能出现在画面里；只有画外音的人不要写进动作和“其余在场者”。
6. 左右站位按上面的站位约定，全场不变，不要这一段在左、下一段在右。
7. 相邻小镜头景别要有变化，不要连着三个都是特写；全集第一段的第一个小镜头要是抓人的动作或特写，不要是慢悠悠的空镜。
8. 心理活动、感受不单独成镜，要落在这个人的表情或手部动作上。
9. 每段 2 到 5 个小镜头；动作、表情、构图只写看得见的东西，不写“氛围感”“压迫感”这类抽象词。

【小镜头格式】每个小镜头一行字符串，9 段用竖线隔开，顺序不能变：
景别|机位|构图|运镜|动作|表情|台词序号|特效边界|其余在场者
台词序号写这个小镜头里响起的台词编号（如 1 或 1,2），没有台词留空；没有特效、没有其他人时对应的段留空。

【输出】只输出一个 JSON 对象：
{{"fixes": [
   {{"seg": 段号,
     "problems": ["这一段有什么问题，一条一句"],
     "beats": ["这一段改好之后的全部小镜头，按时间顺序，每个一行，格式同上"]}}
 ],
 "missing": ["原文里有、但分镜完全没拍到的关键情节，一条一句；没有就给空数组"]}}

要求：
- 只输出需要修改的段；没问题的段不要出现在 fixes 里。全都没问题就输出 {{"fixes": [], "missing": []}}。
- 台词一个字都不许改、不许增删、不许调换顺序。你只能改小镜头。
- beats 要给出该段完整的新小镜头列表（不是只给改动的那一个），每句台词至少被一个小镜头的台词序号引用到。
- 程序检查出的问题必须处理；你自己发现的问题也一并改。

【小说原文】
{novel}

【分镜】
{segments}
"""


# ============================================================
# 第一步：规划
# ============================================================
def _clean(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_plan(raw, novel: str) -> Optional[dict]:
    """模型返回的规划 → 干净的结构；不是这个结构返回 None（调用方退回不带规划的拆法）。

    每场的 start（原文摘录）在全文里定位出起点 offset；定位不到的场次保留但 offset 为 None，
    只用它的场景名和站位，不拿它当分块边界。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("scenes"), list):
        return None
    scenes = []
    cursor = 0
    for i, sc in enumerate(raw["scenes"][:MAX_PLAN_SCENES], start=1):
        if not isinstance(sc, dict):
            continue
        name = _clean(sc.get("name"), 16)
        summary = _clean(sc.get("summary"), 80)
        if not name and not summary:
            continue
        anchor = re.sub(r"\s+", "", str(sc.get("start") or ""))
        offset = None
        if len(anchor) >= MIN_ANCHOR_CHARS:
            offset = _locate(novel, anchor, cursor)
            if offset is not None:
                cursor = offset + 1
        if i == 1 and offset is None:
            offset = 0
        chars = [str(c).strip() for c in (sc.get("characters") or []) if str(c).strip()] \
            if isinstance(sc.get("characters"), list) else []
        scenes.append({"no": len(scenes) + 1, "name": name, "time": _clean(sc.get("time"), 8),
                       "characters": chars[:8], "axis": _clean(sc.get("axis"), 60),
                       "summary": summary, "offset": offset})
    if not scenes:
        return None
    # 只要场次有至少一条可用信息（场景名对应的摘要、站位或定位）才算规划成立
    if not any(s["summary"] or s["axis"] for s in scenes):
        return None
    return {"logline": _clean(raw.get("logline"), 60), "hook": _clean(raw.get("hook"), 60), "scenes": scenes}


def _locate(novel: str, anchor: str, start: int) -> Optional[int]:
    """在原文里找摘录的位置（忽略空白差异）；找不到时用摘录的前 MIN_ANCHOR_CHARS 个字再找一次。"""
    for probe in (anchor, anchor[:MIN_ANCHOR_CHARS]):
        pattern = r"\s*".join(re.escape(ch) for ch in probe)
        m = re.compile(pattern).search(novel, start)
        if m:
            return m.start()
    return None


async def make_plan(llm, novel: str, asset_block: str = "", segment_seconds: int = 15) -> Tuple[Optional[dict], str]:
    """通读全文做规划。返回 (规划或 None, 给用户看的一句说明)。失败不抛。"""
    prompt = PLAN_PROMPT.format(asset_block=asset_block or "（暂无已有资产）", segment_seconds=segment_seconds, novel=novel)
    try:
        raw = await llm.chat_json([{"role": "user", "content": prompt}], max_tokens=PLAN_MAX_TOKENS)
    except Exception as e:                      # 规划是增强项：模型报错、被截断都不影响后面照常拆
        logger.warning("[分镜智能体] 规划失败，按原方式拆：%s", str(e)[:200])
        return None, "全集规划没有成功（模型调用失败），这次按分块各自拆的方式完成"
    plan = normalize_plan(raw, novel)
    if not plan:
        logger.warning("[分镜智能体] 规划返回的结构不可用，按原方式拆")
        return None, "全集规划没有成功（模型返回的结构不对），这次按分块各自拆的方式完成"
    names = "、".join(f"{s['name'] or '第' + str(s['no']) + '场'}" for s in plan["scenes"])
    logger.info("[分镜智能体] 规划 %d 场：%s；钩子：%s", len(plan["scenes"]), names, plan["hook"])
    return plan, f"全集规划：{len(plan['scenes'])} 场（{names}）"


# ============================================================
# 第二步：按规划分块，每块带着规划去拆
# ============================================================
def plan_chunks(plan: Optional[dict], novel: str, chunk_chars: int) -> Optional[List[str]]:
    """按规划的场次边界切块：场与场之间一定断开；一场太长再按原规则切；相邻的短场合并到不超过 chunk_chars。
    规划不可用或只定位到一场时返回 None（调用方用缺省分块）。"""
    if not plan:
        return None
    cuts = sorted({s["offset"] for s in plan["scenes"] if s.get("offset")})
    if not cuts:
        return None
    bounds = [0] + cuts + [len(novel)]
    pieces = [novel[a:b] for a, b in zip(bounds, bounds[1:]) if novel[a:b].strip()]
    chunks: List[str] = []
    for piece in pieces:
        parts = split_novel_chunks(piece, chunk_chars) if len(piece) > chunk_chars else [piece]
        for part in parts:
            # 上一块和这一块加起来还放得下、且上一块很短（不足半块）时并在一起，避免出现几十字的碎块
            if chunks and len(chunks[-1]) < chunk_chars // 2 and len(chunks[-1]) + len(part) <= chunk_chars:
                chunks[-1] += part
            else:
                chunks.append(part)
    return chunks if "".join(chunks) == novel or "".join(chunks).strip() == novel.strip() else None


def scenes_of_chunk(plan: dict, novel: str, chunks: List[str], index: int) -> List[dict]:
    """第 index 块（1 起）覆盖了规划里的哪几场。场次没定位到时返回全部场次。"""
    located = [s for s in plan["scenes"] if s.get("offset") is not None]
    if len(located) < len(plan["scenes"]) or not located:
        return list(plan["scenes"])
    start = sum(len(c) for c in chunks[:index - 1])
    end = start + len(chunks[index - 1])
    out = []
    for i, s in enumerate(located):
        s_end = located[i + 1]["offset"] if i + 1 < len(located) else len(novel)
        if s["offset"] < end and s_end > start:
            out.append(s)
    return out or list(plan["scenes"])


def plan_note(plan: Optional[dict], novel: str, chunks: List[str], index: int) -> str:
    """写进第 index 块提示词的规划说明。没有规划返回空串。"""
    if not plan:
        return ""
    mine = scenes_of_chunk(plan, novel, chunks, index)
    mine_nos = {s["no"] for s in mine}
    lines = ["【全集规划】这一集已经通读过并定了下面的规划，各块都照它拆，场景名和站位不要自己另起："]
    if plan.get("logline"):
        lines.append(f"这一集讲：{plan['logline']}")
    for s in plan["scenes"]:
        head = f"第 {s['no']} 场 {s['name']}" + (f"（{s['time']}）" if s["time"] else "")
        lines.append(f"{head}：{s['summary']}" + ("　←本块在这一场" if s["no"] in mine_nos and len(plan["scenes"]) > 1 else ""))
    for s in mine:
        if s["name"]:
            lines.append(f"本块的场景名统一写“{s['name']}”开头（后面可以接时辰和氛围）。")
        if s["axis"]:
            lines.append(f"站位约定（全场不变）：{s['axis']}")
        if s["characters"]:
            lines.append(f"这一场出场的角色：{'、'.join(s['characters'])}。没列出的角色不要写进画面。")
    before = [s for s in plan["scenes"] if s["no"] < min(mine_nos)]
    if before:
        lines.append("本块之前已经发生：" + "；".join(s["summary"] for s in before if s["summary"]))
    if index == 1 and plan.get("hook"):
        lines.append(f"全集第一段的第一个小镜头用这个画面开场：{plan['hook']}（3 秒内，特写或正在发生的动作）。")
    return "\n".join(lines)


# ============================================================
# 第三步：审片
# ============================================================
def beat_to_text(b: dict) -> str:
    """beat 对象 → 模型写的那种 9 段字符串（给审片的模型看，也是它回写的格式）。"""
    refs = ",".join(str(r) for r in (b.get("line_refs") or []))
    parts = [b.get("shot_size"), b.get("camera"), b.get("composition"), b.get("move"), b.get("action"),
             b.get("expression"), refs, b.get("boundary"), b.get("others")]
    return "|".join(str(p or "").replace("|", "，") for p in parts)


def lint_segment(seg: dict, first: bool = False) -> List[str]:
    """程序能直接看出来的问题（给审片的模型当线索，也让它必须处理）。"""
    beats = [b for b in (seg.get("beats") or []) if isinstance(b, dict)]
    lines = seg.get("lines") or []
    out = []
    if len(beats) < 2 and len(lines) > 1:
        out.append("只有 1 个小镜头，至少拆成 2 个")
    if len(beats) > 5:
        out.append(f"有 {len(beats)} 个小镜头，太碎，合并到 5 个以内")
    for i, b in enumerate(beats, start=1):
        clauses = [c for c in re.split(r"[，,、；;]", str(b.get("action") or "")) if c.strip()]
        if len(clauses) > MAX_ACTION_CLAUSES:
            out.append(f"第 {i} 个小镜头的动作有 {len(clauses)} 个分句，只留 1 个主动作")
        if not str(b.get("action") or "").strip():
            out.append(f"第 {i} 个小镜头没有写动作")
    sizes = [str(b.get("shot_size") or "") for b in beats]
    if any(sizes[i] and sizes[i] == sizes[i + 1] == sizes[i + 2] for i in range(len(sizes) - 2)):
        out.append("连续 3 个小镜头同一景别")
    used = {r for b in beats for r in (b.get("line_refs") or [])}
    lost = [str(i) for i in range(1, len(lines) + 1) if i not in used]
    if lost and beats:
        out.append(f"台词 {'、'.join(lost)} 没有挂在任何小镜头上")
    if first and beats and str(beats[0].get("shot_size") or "") in ("空镜", "远景", "全景", "大远景"):
        out.append("这是全集第一段，第一个小镜头是远景或空镜，换成抓人的特写或动作")
    return out


def segments_for_review(items: List[dict], first_index: int = 1, opening: bool = False) -> str:
    """把一块拆出来的段写成给审片模型看的文本。段号从 first_index 起。"""
    blocks = []
    for k, seg in enumerate(items):
        no = first_index + k
        head = f"段 {no}｜场景：{seg.get('scene') or ''}｜站位：{seg.get('positions') or ''}｜情绪：{seg.get('mood') or ''}"
        lines = [f"  {i}. {ln.get('speaker') or '旁白'}：{ln.get('text') or ''}"
                 for i, ln in enumerate(seg.get("lines") or [], start=1) if isinstance(ln, dict)]
        beats = [f"  - {beat_to_text(b)}" for b in (seg.get("beats") or []) if isinstance(b, dict)]
        issues = lint_segment(seg, first=opening and k == 0)
        block = [head, "台词：", *lines, "小镜头：", *beats]
        if issues:
            block.append("程序检查出的问题：" + "；".join(issues))
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def apply_fixes(items: List[dict], raw, first_index: int = 1) -> Tuple[List[dict], List[str]]:
    """把审片返回的修改应用到段上。返回 (新段列表, 说明列表)。

    只采用安全的修改：段号存在、新小镜头能解析、数量在 1～MAX_BEATS_PER_SEGMENT 之间、
    台词序号不越界、每句台词仍被引用。不满足的整条不采用，保留原样。台词永远不动。
    """
    notes: List[str] = []
    if not isinstance(raw, dict):
        return items, notes
    out = [dict(x) for x in items]
    changed = 0
    for fix in raw.get("fixes") or []:
        if not isinstance(fix, dict):
            continue
        try:
            k = int(fix.get("seg")) - first_index
        except (TypeError, ValueError):
            continue
        if not 0 <= k < len(out) or not isinstance(fix.get("beats"), list):
            continue
        seg = out[k]
        n_lines = len(seg.get("lines") or [])
        beats = _drop_hollow_beats([b for b in (parse_beat(x) for x in fix["beats"] if isinstance(x, str) and x.strip()) if b])
        if not 1 <= len(beats) <= MAX_BEATS_PER_SEGMENT:
            continue
        if any(not str(b.get("action") or "").strip() for b in beats):
            continue
        refs = [r for b in beats for r in (b.get("line_refs") or [])]
        if any(r < 1 or r > n_lines for r in refs) or set(range(1, n_lines + 1)) - set(refs):
            continue                                   # 台词序号越界，或有台词没人引用：不采用
        seg["beats"] = beats
        seg["tail"] = beats[-1].get("action") or seg.get("tail") or ""
        seg.pop("video_prompt", None)                  # 画面时间轴由代码按新小镜头重新生成
        seg.pop("image_prompt", None)
        seg["reviewed"] = [str(p)[:60] for p in (fix.get("problems") or []) if str(p).strip()][:4]
        changed += 1
    if changed:
        notes.append(f"审片改了 {changed} 段的小镜头")
    for m in (raw.get("missing") or [])[:5]:
        if str(m).strip():
            notes.append(f"审片发现原文里有、分镜没拍到的情节：{str(m).strip()[:60]}")
    return out, notes


async def review_chunk(llm, text: str, items: List[dict], note: str = "", first_index: int = 1,
                       opening: bool = False) -> Tuple[List[dict], List[str]]:
    """审一块：返回 (改后的段, 说明)。不是视频段格式、模型报错、返回不对时原样返回，不抛。"""
    if not items or not all(isinstance(x, dict) and x.get("lines") is not None and x.get("beats") is not None for x in items):
        return items, []
    prompt = REVIEW_PROMPT.format(plan_note=note or "（本次没有知识库和全集规划）", novel=text,
                                  segments=segments_for_review(items, first_index, opening))
    try:
        raw = await llm.chat_json([{"role": "user", "content": prompt}],
                                  max_tokens=max(MIN_REVIEW_TOKENS, len(text) * REVIEW_TOKENS_PER_CHAR))
    except Exception as e:
        logger.warning("[分镜智能体] 审片失败，保留拆分结果：%s", str(e)[:200])
        return items, ["有一块的审片没有成功（模型调用失败），这部分保留拆分的原始结果"]
    fixed, notes = apply_fixes(items, raw, first_index)
    return fixed, notes


def summarize_notes(notes: List[str]) -> List[str]:
    """各块的审片说明合并：改了几段加总，其余去重。"""
    total = 0
    rest: Dict[str, None] = {}
    for n in notes:
        m = re.match(r"审片改了 (\d+) 段的小镜头", n)
        if m:
            total += int(m.group(1))
        else:
            rest[n] = None
    out = [f"审片改了 {total} 段的小镜头"] if total else []
    return out + list(rest)
