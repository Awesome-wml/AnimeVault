"""角色形态：固定面部特征（face）+ 若干形态（forms：穿搭 + 出现场次 + 该形态的三视图）。

角色文档字段：
    face        核心固定面部特征（不含服装），用来锁脸
    forms       [{name, outfit, scene_nos:[int], image_path}]，按剧情顺序；只有换装/造型变化才多于 1 个
    voice       音色描述：年龄 + 性别 + 声音属性
    description 旧字段，仍保留（新数据 = face + 第一形态穿搭，供旧消费方和卡片一行说明）
    image_path  旧字段 = 第一形态的三视图，旧代码与旧数据照旧可用

旧数据兼容：没有 forms 的角色视为单形态，outfit 取 description，图取 image_path。
所有读取形态的地方（出图、绑定、接口返回）都经过这里，不各自解析。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

SINGLE_FORM_NAME = "单形态"


def _ints(value) -> List[int]:
    """场次编号：接受整数数组、"1,3,5" 这类字符串或单个数字；去重、保序、丢掉非正数。"""
    if value is None or value == "":
        return []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value]
    if isinstance(value, str):
        value = re.split(r"[,，、\s]+", value.strip())
    if not isinstance(value, (list, tuple)):
        return []
    out: List[int] = []
    for v in value:
        try:
            n = int(float(str(v).strip().strip("第段场")))
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def normalize_form(form, index: int = 0) -> Optional[Dict]:
    """把模型输出 / 请求体里的一个形态规整成固定结构；没有穿搭也没有名字的空项返回 None。"""
    if isinstance(form, str):
        form = {"outfit": form}
    if not isinstance(form, dict):
        return None
    name = str(form.get("name") or "").strip()
    outfit = str(form.get("outfit") or form.get("description") or "").strip()
    if not name and not outfit:
        return None
    return {
        "name": name or f"形态{index + 1}",
        "outfit": outfit,
        "scene_nos": _ints(form.get("scene_nos")),
        "image_path": form.get("image_path") or None,
    }


def normalize_forms(forms) -> List[Dict]:
    out: List[Dict] = []
    for f in forms if isinstance(forms, (list, tuple)) else []:
        n = normalize_form(f, len(out))
        if n:
            out.append(n)
    return out


def character_doc_fields(char: Dict) -> Dict:
    """模型提取结果 → 入库字段（face / forms / voice / description / image_path）。

    新模型给 face + forms；旧模板或用户自建提示词可能只给 description，此时 face 取 description、单形态。
    """
    face = str(char.get("face") or "").strip()
    forms = normalize_forms(char.get("forms"))
    description = str(char.get("description") or "").strip()
    if not forms:
        forms = [{"name": SINGLE_FORM_NAME, "outfit": description, "scene_nos": [], "image_path": None}] \
            if (description or face) else []
    if not face:
        face = description
    if not description:
        description = compose_description(face, forms[0]["outfit"] if forms else "")
    voice = str(char.get("voice") or "").strip()
    return {"face": face, "forms": forms, "voice": voice or None, "description": description,
            "image_path": forms[0].get("image_path") if forms else None}


def compose_description(face: str, outfit: str) -> str:
    """旧字段 description：面部 + 穿搭，给旧消费方和卡片一行说明用。"""
    parts = [p for p in (face.strip(), outfit.strip()) if p]
    return "；穿搭：".join(parts) if len(parts) == 2 else "".join(parts)


def character_forms(char: Dict) -> List[Dict]:
    """角色的形态列表（至少 1 个）。旧数据：单形态，穿搭取 description，图取 image_path。"""
    forms = normalize_forms(char.get("forms"))
    if forms:
        # 第一形态的图与旧字段 image_path 互为镜像：旧数据只写了 image_path 时补回去
        if not forms[0].get("image_path") and char.get("image_path"):
            forms[0]["image_path"] = char["image_path"]
        return forms
    return [{"name": SINGLE_FORM_NAME, "outfit": char.get("description") or "", "scene_nos": [],
             "image_path": char.get("image_path") or None}]


def character_face(char: Dict) -> str:
    return (char.get("face") or char.get("description") or "").strip()


def form_for_scene(char: Dict, scene_no=None) -> Tuple[Dict, Optional[str]]:
    """按段所属场次选形态：scene_nos 命中的形态（多个命中取场次标得最少的）；找不到用第一个形态并给出提示（只有多形态才提示）。

    返回 (形态, 提示或 None)。
    """
    forms = character_forms(char)
    try:
        no = int(scene_no) if scene_no is not None and scene_no != "" else None
    except (TypeError, ValueError):
        no = None
    if no is not None:
        # 两个形态都标了这一场（模型常把“平时的样子”标成全部场次）：取标得最少、最具体的那个
        hits = [f for f in forms if no in f["scene_nos"]]
        if hits:
            return min(hits, key=lambda f: len(f["scene_nos"])), None
    if len(forms) <= 1:
        return forms[0], None
    name = char.get("name") or "角色"
    where = f"第 {no} 场" if no is not None else "本段"
    return forms[0], f"{name} 没有对应{where}的形态，已用第一形态「{forms[0]['name']}」的参考图"


def form_index_of(char: Dict, index: Optional[int]) -> int:
    """出图 / 上传时的形态下标：越界或空取 0。"""
    n = len(character_forms(char))
    try:
        i = int(index or 0)
    except (TypeError, ValueError):
        i = 0
    return i if 0 <= i < n else 0


def set_form_image(char: Dict, index: int, img_path: str) -> Dict:
    """写回某个形态的三视图，返回 $set 用的字段：forms 整体 + 第一形态时同步 image_path。"""
    forms = character_forms(char)
    i = form_index_of(char, index)
    forms[i]["image_path"] = img_path
    update = {"forms": forms}
    if i == 0:
        update["image_path"] = img_path
    return update


def merge_forms_update(char: Dict, forms) -> List[Dict]:
    """接口更新 forms：请求没带 image_path 的形态，按下标沿用原有的图。"""
    old = character_forms(char)
    new = normalize_forms(forms)
    for i, f in enumerate(new):
        if not f.get("image_path") and i < len(old):
            f["image_path"] = old[i].get("image_path")
    return new


def public_forms(char: Dict) -> List[Dict]:
    """接口返回的 forms：旧数据也返回单形态，前端不用再兜底。"""
    return character_forms(char)
