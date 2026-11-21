"""风格 AI 识别：读小说片段，从风格库（core.style_library 的 MEDIUMS / GENRES）里选媒介和题材。

用户不用在新建作品时就选画面类型和题材：作品标记 style_source="auto"（待识别），贴入小说后由这里识别并写回；
用户在风格页手动改过（style_source="user"）就不再自动覆盖。

- 优先调对话模型（注册表环节 style_suggest），结果必须落在风格库 id 里，否则视为失败；
- 模型不可用 / 输出不合法时退回关键词规则（source="rule"），保证总能给出一个结果。
"""
import logging
from typing import Optional

from core.style_library import GENRES, MEDIUMS, get_genre, get_medium

logger = logging.getLogger(__name__)

STYLE_SOURCE_AUTO = "auto"   # 待识别：新建作品没选风格
STYLE_SOURCE_AI = "ai"       # 已由 AI / 规则识别
STYLE_SOURCE_USER = "user"   # 用户手动选过：不再自动覆盖

MIN_TEXT_CHARS = 200         # 正文太短识别不准，不自动识别
EXCERPT_HEAD = 2400
EXCERPT_TAIL = 800

# 关键词兜底：题材 id → 词表（命中次数最多的题材胜出）
_GENRE_KEYWORDS = {
    "xianxia": ("修仙", "修炼", "灵力", "灵气", "御剑", "宗门", "师门", "渡劫", "飞升", "修为", "丹药", "法宝", "阵法", "仙", "魔气"),
    "xuanhuan": ("境界", "斗气", "血脉", "秘境", "魔兽", "天才", "突破", "玄", "功法"),
    "mojueshi": ("末世", "丧尸", "废土", "变异", "避难所", "物资", "感染"),
    "dushi": ("总裁", "公司", "董事长", "豪车", "别墅", "保镖", "集团", "都市"),
    "xuanyi": ("凶手", "尸体", "线索", "警察", "推理", "侦探", "失踪", "案子", "嫌疑"),
    "gaoxiao": ("搞笑", "沙雕", "哈哈", "无语", "社死"),
    "gufeng": ("皇上", "王爷", "嫔妃", "侯府", "嫡女", "庶女", "朝堂", "圣旨", "本宫", "宫中", "太后"),
    "jiating": ("婆婆", "儿媳", "婆媳", "彩礼", "亲戚", "偏心", "小姑子", "妯娌"),
    "tianchong": ("心动", "告白", "前任", "婚约", "娇妻", "宠溺", "暗恋"),
    "zhichang": ("经理", "同事", "升职", "加班", "背锅", "汇报", "项目组", "KPI"),
    "chongsheng": ("重生", "前世", "上一世", "上辈子", "重来一次"),
}
# 规则兜底时题材 → 媒介：修仙玄幻末世特效多走 3D 国漫，其余走产品主线真人实拍
_GENRE_MEDIUM = {"xianxia": "cg3d", "xuanhuan": "cg3d", "mojueshi": "cg3d"}
_DEFAULT_MEDIUM = "realistic"


def novel_excerpt(text: str) -> str:
    """开头 + 结尾片段（长文不全塞，题材和世界观看开头、结尾足够）。"""
    t = (text or "").strip()
    if len(t) <= EXCERPT_HEAD + EXCERPT_TAIL:
        return t
    return t[:EXCERPT_HEAD] + "\n……（中间省略）……\n" + t[-EXCERPT_TAIL:]


def medium_options() -> str:
    return "\n".join(f"{m['id']}｜{m['name']}｜{m['description']}" for m in MEDIUMS)


def genre_options() -> str:
    return "\n".join(f"{g['id']}｜{g['name']}｜{g['description']}" for g in GENRES)


def _result(medium_id: str, genre_def: dict, confidence: float, reason: str, source: str) -> dict:
    m = get_medium(medium_id) or get_medium(_DEFAULT_MEDIUM)
    return {
        "medium": m["id"], "medium_name": m["name"],
        "genre": genre_def["genre"], "genre_id": genre_def["id"], "genre_name": genre_def["name"],
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 2),
        "reason": str(reason or "").strip()[:120],
        "source": source,
    }


def parse_suggestion(result) -> Optional[dict]:
    """模型输出 → 规范结果；媒介或题材不在风格库里返回 None。"""
    if not isinstance(result, dict):
        return None
    m = get_medium(str(result.get("medium") or "").strip())
    g = get_genre(str(result.get("genre") or "").strip())
    if not m or not g:
        return None
    try:
        conf = float(result.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.6
    return _result(m["id"], g, conf, result.get("reason"), "ai")


def rule_suggestion(text: str) -> dict:
    """关键词兜底：数各题材词表命中次数；都没命中按都市 + 真人实拍。"""
    t = text or ""
    scores = {gid: sum(t.count(w) for w in words) for gid, words in _GENRE_KEYWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if not scores[best]:
        g = get_genre("dushi")
        return _result(_DEFAULT_MEDIUM, g, 0.3, "正文里没有明显的题材特征词，按都市现实题材处理", "rule")
    g = get_genre(best)
    hits = [w for w in _GENRE_KEYWORDS[best] if w in t][:4]
    conf = 0.4 + 0.4 * scores[best] / max(total, 1)
    return _result(_GENRE_MEDIUM.get(best, _DEFAULT_MEDIUM), g, conf,
                   f"正文多次出现“{'、'.join(hits)}”等{g['name']}特征词", "rule")


async def suggest_style(llm, text: str, model: Optional[str] = None) -> dict:
    """识别风格：先问模型，失败退回规则。llm 为空时直接用规则。"""
    if llm is not None:
        try:
            from core.prompt_registry import build_messages
            messages = build_messages("style_suggest", novel_excerpt=novel_excerpt(text),
                                      medium_options=medium_options(), genre_options=genre_options())
            kwargs = {"max_tokens": 600}
            if model:
                kwargs["model"] = model
            parsed = parse_suggestion(await llm.chat_json(messages, **kwargs))
            if parsed:
                return parsed
            logger.warning("[风格识别] 模型输出不在风格库里，改用关键词规则")
        except Exception as e:  # noqa: BLE001  识别失败不能挡住主流程
            logger.warning("[风格识别] 模型调用失败，改用关键词规则: %s", e)
    return rule_suggestion(text)


def needs_auto(project: dict) -> bool:
    """作品是否在等待自动识别风格（新建时没选）。老作品没有这个字段，视为用户已选。"""
    return (project or {}).get("style_source") == STYLE_SOURCE_AUTO


def apply_fields(s: dict) -> dict:
    """写回作品的字段：媒介、题材、来源、理由；旧 style 字段清空。"""
    return {"medium": s["medium"], "genre": s["genre"], "style": "", "style_source": STYLE_SOURCE_AI,
            "style_reason": f"{s['medium_name']} · {s['genre_name']}：{s['reason']}".strip("：")}


async def auto_style_if_needed(db, project: dict, llm, text: str) -> Optional[dict]:
    """作品待识别且正文够长时识别并写回，返回识别结果；否则返回 None。不抛异常。"""
    if not needs_auto(project) or len((text or "").strip()) < MIN_TEXT_CHARS:
        return None
    try:
        s = await suggest_style(llm, text)
        fields = apply_fields(s)
        await db.projects.update_one({"_id": project["_id"]}, {"$set": fields})
        project.update(fields)
        logger.info(f"[风格识别] 自动识别为 {fields['style_reason']}（来源 {s['source']}）")
        return s
    except Exception as e:  # noqa: BLE001
        logger.warning("[风格识别] 自动识别失败，沿用缺省风格: %s", e)
        return None
