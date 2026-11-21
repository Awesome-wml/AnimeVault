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
