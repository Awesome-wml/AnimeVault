"""提示词注册表加载层（文件化，不再读 DB prompts 集合）。

两层文件：
- system.json    S 骨架：角色身份 + 返回契约（JSON 结构/字段/枚举/示例）+ 数据占位声明。固定，不可被题材或用户覆盖。
- constraints.json C 约束：内置 default + 题材 variants，是可在管理侧维护的中段要求；image 类的整段出图描述也放这里。

D 数据（小说/剧本原文、风格块、资产清单、时长参数等）由调用方运行时填入占位符，不落文件。

环节类型 kind：
- json：  system 消息 = 身份 + 契约；user 消息 = 约束 + 数据块。
- text：  system 消息 = 身份 + 文体要求（无 JSON 契约）；user 消息 = 约束 + 数据块。
- image： 无 system/契约，build_prompt_text 返回填充后的单条出图文本。
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
_PROMPT_DIR = os.path.join(_DIR, "prompts")
_SYSTEM_FILE = os.path.join(_PROMPT_DIR, "system.json")
_CONSTRAINT_FILE = os.path.join(_PROMPT_DIR, "constraints.json")

_cache = {}
_PH_RE = re.compile(r"\{([a-z_]+)\}")
_UNFILLED_RE = _PH_RE
_ANY_PH_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _load(path: str) -> dict:
    if path not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache[path] = json.load(f)
    return _cache[path]


def _fill(text: str, data: dict) -> str:
    """逐占位符替换；缺占位符或缺值都不抛错。不走 str.format，契约示例花括号不受影响。

    data 未覆盖的 {xxx} 占位符末尾清空，避免缺值时把占位符原样留在请求里。
    """
    if not text:
        return ""

    def _sub(m):
        key = m.group(1)
        if key in data:
            v = data[key]
            return "" if v is None else str(v)
        # 未提供的小写占位符清空；其他花括号内容（契约示例等）原样保留
        return "" if _UNFILLED_RE.fullmatch(m.group(0)) else m.group(0)

    # 单次扫描：只替换模板里的占位符，插进去的值（小说原文、剧本）不再被二次扫描，
    # 原文里恰好出现的 {person_rule}、{abc} 等不会被替换或删掉
    return _ANY_PH_RE.sub(_sub, text)


def get_entry(key: str, variant: str = None) -> dict:
    """取某环节的骨架与约束；variant（题材）命中变体时在默认约束后追加，契约始终沿用骨架。"""
    sys_doc = _load(_SYSTEM_FILE)
    con_doc = _load(_CONSTRAINT_FILE)
    s = sys_doc.get("prompts", {}).get(key)
    if not s:
        raise KeyError(f"未注册的提示词环节: {key}")

    c = con_doc.get("prompts", {}).get(key, {}) or {}
    constraint = c.get("default", "") or ""
    variants = c.get("variants") or {}
    # 题材变体默认在默认约束之后追加补充；需要整段替换时变体写成 {"replace": true, "text": "..."}。
    if variant and variants.get(variant):
        v = variants[variant]
        if isinstance(v, dict) and v.get("replace"):
            constraint = v.get("text", "")
        elif v:
            constraint = (constraint + "\n\n" + v) if constraint else v

    return {
        "kind": s.get("kind", "text"),
        "system": s.get("system", "") or "",
        "contract": s.get("contract", "") or "",
        "constraint": constraint,
        "placeholders": s.get("placeholders", []),
        "data_blocks": s.get("data_blocks", []),
    }


def resolve_prompt(prompt_id: str, default_key: str) -> tuple:
    """把前端所选提示词 ID（环节 key，或 `key:题材变体`）解析成 (环节key, 变体)。
    空、未注册或格式不符时回退默认环节，避免传错 ID 导致 get_entry 报错。"""
    if not prompt_id:
        return default_key, None
    pid = str(prompt_id).strip()
    sys_doc = _load(_SYSTEM_FILE).get("prompts", {})
    key, sep, variant = pid.partition(":")
    if sep and key in sys_doc:
        return key, (variant or None)
    if pid in sys_doc:
        return pid, None
    if key in sys_doc:
        return key, None
    logger.warning("提示词 ID 未注册，回退默认环节: %s", prompt_id)
    return default_key, None


def _user_content(e: dict, data: dict) -> str:
    parts = [e["constraint"]]
    for block in e["data_blocks"]:
        ph = block.get("placeholder")
        label = block.get("label")
        val = data.get(ph)
        if val is None or str(val).strip() == "":
            continue
        parts.append(f"【{label}】\n{val}" if label else str(val))
    return _fill("\n\n".join(x for x in parts if x), data)


def build_messages(key: str, variant: str = None, **data) -> list:
    """拼装发给对话模型的 messages：[{role:system}, {role:user}]（json / text 类）。

    variant：题材，用于选 constraints 变体；业务占位符（如小说题材 genre）放进 data。
    """
    e = get_entry(key, variant)
    system_content = _fill("\n\n".join(x for x in (e["system"], e["contract"]) if x), data)
    user_content = _user_content(e, data)

    messages = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": user_content})
    return messages


def build_prompt_text(key: str, variant: str = None, **data) -> str:
    """image 类：返回填充后的单条出图文本（无 system、无契约）。"""
    e = get_entry(key, variant)
    return _fill(e["constraint"], data).strip()
