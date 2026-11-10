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
    out = text
    for k, v in data.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    out = _PH_RE.sub(lambda m: "" if m.group(1) not in data else m.group(0), out)
    return out


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
