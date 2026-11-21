"""重复角色：同一个人被提取成两个角色（“白衣男子”和“白衣阴冷男子”），找出来、合并掉。

提取去重（core/asset_merge）只认名字一字不差的；模型对同一个无名角色两次起的称呼常常不一样，
于是出现两张卡、两套三视图，拆分镜时一会儿绑这个一会儿绑那个，视频里脸对不上。

- rule_groups：不调模型的粗筛——一个名字的字按顺序都出现在另一个名字里，且性别不冲突；
- ai_groups：让模型对着原文判断哪些称呼是同一个人（能认出“铁面具”和“封家刀客”这种名字完全不同的）；
- merge_plan：合并后的角色怎么写——保留的那个为准，空着的字段从别的补，别的角色出过的三视图作为形态并进来不丢；
- rename_refs：分镜、剧本、全集规划里出现的旧名字换成保留的名字。

合并会删掉被并入的角色，所以只给建议，由用户点了才做。
"""
import logging
import re
from typing import Dict, List, Optional

from core.asset_merge import norm_name, _empty

logger = logging.getLogger(__name__)

PROMPT_KEY = "character_dedupe"
MIN_NAME = 2
MIN_RATIO = 0.5               # 短名字至少占长名字的一半，“他”“男子”这种太泛的不算
FILL_FIELDS = ("face", "description", "voice", "voice_design", "voice_design_source", "voice_name",
               "gender", "age_group", "trait", "image_path")
# 分镜、剧本文档里不做名字替换的字段（路径、id、时间）
_SKIP_KEYS = re.compile(r"(^_id$|_id$|^id$|_path$|^path$|_time$|^video_set_id$|^model_key$|^review$)")
_RANK = {"main": 0, "support": 1, "extra": 2}


def _subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _same_gender(a: dict, b: dict) -> bool:
    ga, gb = str(a.get("gender") or "").lower(), str(b.get("gender") or "").lower()
    return not (ga and gb and ga != gb)


def similar_names(a: str, b: str) -> bool:
    """两个名字像不像同一个人：短的那个每个字按顺序都在长的里（白衣男子 ⊂ 白衣阴冷男子）。"""
    a, b = norm_name(a), norm_name(b)
    if not a or not b or a == b:
        return False
    short, long = sorted((a, b), key=len)
    return len(short) >= MIN_NAME and len(short) / len(long) >= MIN_RATIO and _subsequence(short, long)


def _group(chars: List[dict], pairs: List[tuple]) -> List[List[dict]]:
    """成对的关系并成组（并查集）。"""
    parent = list(range(len(chars)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in pairs:
        parent[find(i)] = find(j)
    groups: Dict[int, List[dict]] = {}
    for i, c in enumerate(chars):
        groups.setdefault(find(i), []).append(c)
    return [g for g in groups.values() if len(g) > 1]


def suggest_keep(group: List[dict]) -> dict:
    """建议保留哪一个：戏份重的、出过三视图的、资料全的优先；都一样取名字短的。"""
    def score(c):
        has_image = bool(c.get("image_path") or any((f or {}).get("image_path") for f in c.get("forms") or []))
        filled = sum(1 for k in ("face", "description", "voice_design", "voice_name") if not _empty(c.get(k)))
        return (_RANK.get(str(c.get("importance") or "support"), 1), not has_image, -filled, len(norm_name(c.get("name"))))
    return min(group, key=score)


def _suggestion(group: List[dict], reason: str, source: str) -> dict:
    keep = suggest_keep(group)
    return {"names": [c.get("name") for c in group], "ids": [str(c.get("_id")) for c in group],
            "keep": keep.get("name"), "keep_id": str(keep.get("_id")), "reason": reason, "source": source}


def rule_groups(chars: List[dict]) -> List[dict]:
    """名字相近的角色分组。返回 [{"names", "ids", "keep", "keep_id", "reason", "source": "rule"}]。"""
    chars = [c for c in chars or [] if isinstance(c, dict) and c.get("name")]
    pairs = [(i, j) for i in range(len(chars)) for j in range(i + 1, len(chars))
             if similar_names(chars[i]["name"], chars[j]["name"]) and _same_gender(chars[i], chars[j])]
    return [_suggestion(g, "名字很像，可能是同一个人被提取了两次", "rule") for g in _group(chars, pairs)]


def cast_block(chars: List[dict]) -> str:
    from core.character_forms import character_face
    out = []
    for c in chars:
        bits = [x for x in (str(c.get("gender") or ""), str(c.get("age_group") or ""),
                            str(character_face(c) or c.get("description") or "")[:50]) if x]
        out.append(f"- {c.get('name')}" + (f"：{'，'.join(bits)}" if bits else ""))
    return "\n".join(out)


async def ai_groups(llm, chars: List[dict], novel: str = "", variant: Optional[str] = None) -> List[dict]:
    """让模型对着原文判断哪些角色其实是同一个人。失败返回空列表（不抛）。"""
    from core.prompt_registry import build_messages
    chars = [c for c in chars or [] if isinstance(c, dict) and c.get("name")]
    if len(chars) < 2:
        return []
    messages = build_messages(PROMPT_KEY, variant=variant, cast_block=cast_block(chars),
                              novel_text=(novel or "")[:6000] or "（未提供）")
    try:
        raw = await llm.chat_json(messages, max_tokens=2048)
    except Exception as e:
        logger.warning("AI 查重复角色失败: %s", e)
        return []
    by_name = {norm_name(c["name"]): c for c in chars}
    out, used = [], set()
    for it in (raw.get("same") if isinstance(raw, dict) else None) or []:
        if not isinstance(it, dict) or not isinstance(it.get("names"), list):
            continue
        group = []
        for n in it["names"]:
            c = by_name.get(norm_name(n))
            if c is not None and id(c) not in used and c not in group:
                group.append(c)
        if len(group) < 2:
            continue
        used.update(id(c) for c in group)
        reason = re.sub(r"[\"\r\n]", "", str(it.get("reason") or "")).strip()[:60] or "模型判断是同一个人"
        out.append(_suggestion(group, reason, "ai"))
    return out


def combine(*lists: List[dict]) -> List[dict]:
    """多路建议合在一起：同一组人（不管顺序）只留第一次出现的（先传的优先，AI 的理由更具体就先传 AI 的）。"""
    seen, out = set(), []
    for lst in lists:
        for g in lst or []:
            key = frozenset(g["ids"])
            if key in seen or any(key & k for k in seen):
                continue
            seen.add(key)
            out.append(g)
    return out


def merge_plan(keep: dict, others: List[dict]) -> dict:
    """把 others 并进 keep：返回 keep 要更新的字段。

    - keep 填过的不动，空着的从 others 按顺序补；
    - others 出过三视图的形态并进来（一张图都不丢），单形态的用它原来的角色名当形态名；没图的形态不带，免得多出空形态；
    - others 的名字记进 aliases（别名），以后提取出同一个称呼时好认。
    """
    from core.character_forms import character_forms, normalize_forms, SINGLE_FORM_NAME
    update: Dict = {}
    for key in FILL_FIELDS:
        if _empty(keep.get(key)):
            for o in others:
                if not _empty(o.get(key)):
                    update[key] = o[key]
                    break
    forms = character_forms(keep)
    names = {f["name"] for f in forms}
    added = False
    for o in others:
        for f in character_forms(o):
            if not f.get("image_path"):
                continue
            name = f["name"] if f["name"] and f["name"] != SINGLE_FORM_NAME else str(o.get("name") or "")
            if name in names:
                name = f"{o.get('name')}·{name}"
            names.add(name)
            forms.append({**f, "name": name, "scene_nos": f.get("scene_nos") or []})
            added = True
    if added:
        # keep 原来是旧数据（没有 forms 字段）时，第一形态补个名字，和并进来的区分开
        if forms[0]["name"] == SINGLE_FORM_NAME and not normalize_forms(keep.get("forms")):
            forms[0]["name"] = str(keep.get("name") or SINGLE_FORM_NAME)
        update["forms"] = forms
    aliases = [str(a) for a in keep.get("aliases") or []]
    for o in others:
        for a in [o.get("name")] + list(o.get("aliases") or []):
            if a and a not in aliases and a != keep.get("name"):
                aliases.append(str(a))
    if aliases != list(keep.get("aliases") or []):
        update["aliases"] = aliases
    best = min([keep] + others, key=lambda c: _RANK.get(str(c.get("importance") or "support"), 1)).get("importance")
    if best and best != keep.get("importance"):
        update["importance"] = best
    return update


def rename_refs(value, old: str, new: str):
    """文档里出现的旧名字换成新名字（字符串、列表、字典的键都换），返回 (新值, 是否改过)。

    新名字里本来就包含旧名字时（“沈砚” → “沈砚之”），已经是新名字的地方不再重复替换。
    列表改完后去重（同一段里两个名字都在，合并后只留一个）。
    """
    if not old or old == new:
        return value, False
    if isinstance(value, str):
        if old not in value:
            return value, False
        if old in new:
            mark = "\u0000"
            out = value.replace(new, mark).replace(old, new).replace(mark, new)
        else:
            out = value.replace(old, new)
        return out, out != value
    if isinstance(value, list):
        changed, out = False, []
        for v in value:
            nv, c = rename_refs(v, old, new)
            changed = changed or c
            out.append(nv)
        if changed and all(isinstance(x, str) for x in out):
            out = list(dict.fromkeys(out))    # 名字列表改名后可能重复（两个名字都在）：只留一个
        return (out, True) if changed else (value, False)
    if isinstance(value, dict):
        changed, out = False, {}
        for k, v in value.items():
            if isinstance(k, str) and _SKIP_KEYS.search(k):
                out[k] = v
                continue
            nk = new if k == old else k
            nv, c = rename_refs(v, old, new)
            changed = changed or c or nk != k
            out.setdefault(nk, nv)
        return (out, True) if changed else (value, False)
    return value, False
