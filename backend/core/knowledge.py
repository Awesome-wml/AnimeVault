"""作品知识库：小说的角色、场景、道具、规划是互相关联的一份资料，不是各做各的。

拆分镜的三步（规划、拆分、审片）读的是同一份知识库文本：
- 角色卡：身份、性别年龄、面部特征、各形态的穿搭和适用场次，以及和他相关的道具；
- 场景卡：环境描述，以及在这里出场的角色（来自全集规划或剧本场次）；
- 道具卡：外形描述，以及持有或相关的角色。
关联是按名字互相出现算出来的（道具描述里提到某个角色、角色设定里提到某件道具、规划里某场列了哪些角色）。

这样模型知道“铁面具戴着铁面具、提长刀”“玉牌是沈砚的”，而不是只拿到一串名字自己猜。
"""
import re
from typing import Dict, List, Optional

MAX_FACE = 60
MAX_OUTFIT = 50
MAX_DESC = 70
MAX_KNOWLEDGE_CHARS = 3500      # 整份知识库文本的上限，超了从道具、场景描述开始压短
GENDER_CN = {"male": "男", "female": "女"}
ROLE_CN = {"main": "主角", "support": "配角", "extra": "路人"}


def _short(text, n: int) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n].rstrip("，,；; ")


def _uniq(items: List[dict]) -> List[dict]:
    return list({a.get("name"): a for a in items if a.get("name")}.values())


def build_relations(chars: List[dict], scenes: List[dict], props: List[dict], plan: Optional[dict] = None,
                    scripts: Optional[List[dict]] = None) -> Dict:
    """资产之间的关联：{"prop_owners": {道具: [角色]}, "char_props": {角色: [道具]}, "scene_cast": {场景: [角色]}}。"""
    from core.character_forms import character_face, character_forms

    char_names = [c["name"] for c in _uniq(chars)]
    prop_owners: Dict[str, List[str]] = {}
    char_props: Dict[str, List[str]] = {n: [] for n in char_names}
    char_text = {}
    for c in _uniq(chars):
        outfits = " ".join(str(f.get("outfit") or "") for f in character_forms(c))
        char_text[c["name"]] = f"{character_face(c)} {c.get('description') or ''} {outfits}"
    for p in _uniq(props):
        desc = f"{p.get('description') or ''} {p.get('owner') or ''}"
        owners = [n for n in char_names if n in desc or p["name"] in char_text.get(n, "")]
        prop_owners[p["name"]] = owners
        for n in owners:
            char_props[n].append(p["name"])
    scene_cast: Dict[str, List[str]] = {}
    for s in (plan or {}).get("scenes") or []:
        for sc in _uniq(scenes):
            if sc["name"] and (sc["name"] in (s.get("name") or "") or (s.get("name") or "") in sc["name"]) and s.get("name"):
                cast = scene_cast.setdefault(sc["name"], [])
                cast.extend(n for n in (s.get("characters") or []) if n in char_names and n not in cast)
    for s in scripts or []:
        loc = str(s.get("location") or "")
        for sc in _uniq(scenes):
            if sc["name"] and (sc["name"] in loc or (loc and loc in sc["name"])):
                cast = scene_cast.setdefault(sc["name"], [])
                names = s.get("characters") or []
                cast.extend(n for n in names if n in char_names and n not in cast)
    return {"prop_owners": prop_owners, "char_props": char_props, "scene_cast": scene_cast}


def knowledge_text(chars: List[dict], scenes: List[dict], props: List[dict], plan: Optional[dict] = None,
                   scripts: Optional[List[dict]] = None, limit: int = MAX_KNOWLEDGE_CHARS) -> str:
    """整份知识库文本。没有任何资产返回空串。"""
    from core.character_forms import character_face, character_forms

    chars, scenes, props = _uniq(chars or []), _uniq(scenes or []), _uniq(props or [])
    if not (chars or scenes or props):
        return ""
    rel = build_relations(chars, scenes, props, plan, scripts)

    def render(face_n: int, desc_n: int) -> str:
        out = ["【作品知识库】下面的角色、场景、道具设定互相关联，拆分镜时人物长相穿着、场景样子、谁拿着什么都以它为准："]
        if chars:
            out.append("角色：")
            for c in chars:
                tags = "，".join(t for t in (ROLE_CN.get(str(c.get("importance") or "")), GENDER_CN.get(str(c.get("gender") or "").lower()),
                                            str(c.get("age_group") or "").strip()) if t)
                bits = [f"- {c['name']}" + (f"（{tags}）" if tags else "")]
                face = _short(character_face(c), face_n)
                if face:
                    bits.append(f"长相：{face}")
                forms = character_forms(c)
                for f in forms:
                    outfit = _short(f.get("outfit"), MAX_OUTFIT)
                    if not outfit or outfit == face:
                        continue
                    nos = "、".join(str(n) for n in (f.get("scene_nos") or []))
                    name = f.get("name") or "默认"
                    bits.append(f"形态「{name}」穿：{outfit}" + (f"（第 {nos} 场）" if nos and len(forms) > 1 else ""))
                if rel["char_props"].get(c["name"]):
                    bits.append("相关道具：" + "、".join(rel["char_props"][c["name"]]))
                out.append("；".join(bits))
        if scenes:
            out.append("场景：")
            for s in scenes:
                bits = [f"- {s['name']}"]
                desc = _short(s.get("description"), desc_n)
                if desc:
                    bits.append(desc)
                if rel["scene_cast"].get(s["name"]):
                    bits.append("在这里出场：" + "、".join(rel["scene_cast"][s["name"]]))
                out.append("；".join(bits))
        if props:
            out.append("道具：")
            for p in props:
                bits = [f"- {p['name']}"]
                desc = _short(p.get("description"), desc_n)
                if desc:
                    bits.append(desc)
                if rel["prop_owners"].get(p["name"]):
                    bits.append("相关角色：" + "、".join(rel["prop_owners"][p["name"]]))
                out.append("；".join(bits))
        return "\n".join(out)

    text = render(MAX_FACE, MAX_DESC)
    for face_n, desc_n in ((40, 40), (30, 20), (20, 0)):
        if len(text) <= limit:
            break
        text = render(face_n, desc_n)
    return text[:limit]


# ============================================================
# 出图、出视频时按“这一段”取知识库：这一段属于规划里的哪一场、站位怎么约定、出镜的人长什么样、道具归谁
# ============================================================
SEG_FACE = 36
SEG_OUTFIT = 36
SEG_PROP = 30


def plan_for(project: Optional[dict], video_set_id=None) -> Optional[dict]:
    """拆分镜时存回作品的全集规划（按集）。没有返回 None。"""
    plans = (project or {}).get("shot_plans")
    if not isinstance(plans, dict):
        return None
    plan = plans.get(str(video_set_id)) if video_set_id else None
    plan = plan or plans.get("default")
    return plan if isinstance(plan, dict) and isinstance(plan.get("scenes"), list) else None


def plan_scene_of(plan: Optional[dict], seg: dict) -> Optional[dict]:
    """这一段属于规划里的哪一场：按场景名对（拆分时每块都被要求用规划的场景名开头）。
    全集只有一场时直接就是它；对不上返回 None（不猜）。"""
    scenes = [s for s in ((plan or {}).get("scenes") or []) if isinstance(s, dict)]
    if not scenes:
        return None
    text = str(seg.get("scene") or "")
    hits = [s for s in scenes if s.get("name") and s["name"] in text]
    if hits:
        return max(hits, key=lambda s: len(s["name"]))
    return scenes[0] if len(scenes) == 1 else None


def forms_for_segment(seg: dict, chars: List[dict], plan: Optional[dict] = None) -> Dict[str, str]:
    """这一段每个多形态角色用哪个形态：{角色名: 形态名}。

    依据是全集规划里这一场的 wear（规划时模型看着各形态的名字和穿搭定的）；形态名要在角色资产里对得上才算。
    只有一个形态的角色、规划里没写的角色不出现（下游按场次号或第一形态处理）。
    """
    from core.character_forms import character_forms, match_form
    wear = (plan_scene_of(plan, seg) or {}).get("wear") or {}
    out: Dict[str, str] = {}
    by_char = {c.get("name"): c for c in chars or [] if isinstance(c, dict)}
    for name in [str(x) for x in (seg.get("characters") or []) if x]:
        c = by_char.get(name)
        if not c or len(character_forms(c)) <= 1 or not wear.get(name):
            continue
        hit = match_form(c, wear[name])
        if hit:
            out[name] = hit["name"]
    return out


def clean_segment_forms(forms, chars: List[dict]) -> Dict[str, str]:
    """用户在分镜里手选的形态 → 只留角色和形态名都对得上的。"""
    from core.character_forms import match_form
    by_char = {c.get("name"): c for c in chars or [] if isinstance(c, dict)}
    out = {}
    for name, form in (forms or {}).items() if isinstance(forms, dict) else []:
        hit = match_form(by_char.get(name) or {}, form) if by_char.get(name) else None
        if hit:
            out[str(name)] = hit["name"]
    return out


def segment_knowledge(seg: dict, chars: List[dict], scenes: List[dict], props: List[dict],
                      plan: Optional[dict] = None, people: Optional[List[str]] = None,
                      narrator: str = "") -> Dict:
    """这一段要用到的知识库内容。

    返回 {"axis": 站位约定, "scene_name": 规划的场景名, "cast": ["沈砚：长相…，穿…"], "props": ["残缺玉牌：…（沈砚的）"]}。
    cast 的措辞每一段都一样（同一个角色同一个形态逐字相同），视频模型才会把各段认成同一个人。
    people：这一段出镜的人（不传取 seg.characters）；只有画外音的人不该传进来。
    另带 "voices"：{说话人: 声音设定那一句}（这一段有台词的角色，画外音也算；core.voice_design），
    "narrator"：作品设的旁白声音（没设为空，由提示词用缺省）。
    """
    from core.character_forms import character_face, form_for_scene

    by_char = {c.get("name"): c for c in _uniq(chars or [])}
    by_prop = {p.get("name"): p for p in _uniq(props or [])}
    sc = plan_scene_of(plan, seg)
    rel = build_relations(chars or [], scenes or [], props or [], plan)
    cast = []
    for name in (people if people is not None else [str(x) for x in (seg.get("characters") or []) if x]):
        c = by_char.get(name)
        if not c:
            continue
        form, _ = form_for_scene(c, seg.get("scene_no"), prefer=(seg.get("forms") or {}).get(name))
        face = _short(character_face(c), SEG_FACE)
        outfit = _short(form.get("outfit"), SEG_OUTFIT)
        bits = [x for x in (face, f"穿{outfit}" if outfit and outfit != face else "") if x]
        if bits:
            cast.append(f"{name}：{'，'.join(bits)}")
    prop_lines = []
    for name in [str(x) for x in (seg.get("props") or []) if x]:
        p = by_prop.get(name)
        if not p:
            continue
        desc = _short(p.get("description"), SEG_PROP)
        owners = rel["prop_owners"].get(name) or []
        tail = f"（{'、'.join(owners)}的）" if owners else ""
        if desc or tail:
            prop_lines.append(f"{name}：{desc}{tail}" if desc else f"{name}{tail}")
    from core.voice_design import voices_for
    speakers = list(dict.fromkeys(str(ln.get("speaker")) for ln in (seg.get("lines") or [])
                                  if isinstance(ln, dict) and ln.get("speaker")))
    return {"axis": _short((sc or {}).get("axis"), 60), "scene_name": (sc or {}).get("name") or "",
            "cast": cast, "props": prop_lines,
            "voices": voices_for(speakers, list(by_char.values())), "narrator": narrator or ""}


def knowledge_line(k: Optional[Dict]) -> str:
    """写进视频提示词的一行：角色与道具设定。没有内容返回空串。"""
    if not k:
        return ""
    parts = list(k.get("cast") or [])
    if k.get("props"):
        parts.append("道具 " + "；".join(k["props"]))
    return "；".join(parts)


# ============================================================
# 站位：规划定了“谁在左、谁在右”，某一段自己写的站位和它相反就是冲突
# ============================================================
_SIDE = re.compile(r"[左右]")
_FACING = "朝向往对"          # “面朝右”“看向左”里的左右是朝向，不是站位


def sides_of(text: str, names: List[str]) -> Dict[str, str]:
    """从一句站位文字里读出每个人站在哪一侧：{"沈砚": "左", "铁面具": "右"}。读不出的人不在结果里。

    规则：人名之后、同一个分句里第一个不是朝向的“左/右”。“沈砚在画面左侧面朝右”→ 左。"""
    out: Dict[str, str] = {}
    text = str(text or "")
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        for m in re.finditer(re.escape(name), text):
            clause = re.split(r"[，,；;。]", text[m.end():], maxsplit=1)[0]
            for sm in _SIDE.finditer(clause):
                if sm.start() > 0 and clause[sm.start() - 1] in _FACING:
                    continue
                out.setdefault(name, sm.group(0))
                break
            if name in out:
                break
    return out


def axis_conflicts(axis: str, positions: str, names: List[str]) -> List[str]:
    """站位与约定相反的人，写成给人看的句子。约定或站位里没写到的人不算。"""
    want, got = sides_of(axis, names), sides_of(positions, names)
    return [f"{n} 按约定在{want[n]}侧，这一段写在了{got[n]}侧" for n in names if n in want and n in got and want[n] != got[n]]
