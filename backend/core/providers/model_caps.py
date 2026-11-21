"""模型能力表：思考（thinking）参数的统一兼容层。规则只写在这里，llm_provider 只调用它。

能力分三种（resolve_thinking 返回要并进请求体的字段）：
- switchable：可开可关。结构化调用传 "thinking":{"type":"disabled"}，要思考时传 {"type":"enabled"}。
  官方口径：GLM-5.2/5.1/5/5-Turbo/5v-Turbo、GLM-4.6/4.6V/4.5。
- always：强制思考，不可关。结构化调用传最低档 "reasoning_effort":"low"。
  官方口径：GLM-5.3 系列、GLM-4.7、GLM-4.5V。
  实测 glm-5.3-flashx：thinking={"type":"low"} 同样回 1210；顶层 reasoning_effort=low 才生效（思考 tokens≈0），
  不传时默认深度思考，8192 tokens 全被思考吃掉、正文 0 字。
- none：不认这些参数（或未知）。一律不传，交给供应商默认。

判定顺序：模型预设上的手动档位（自动 / 关闭 / low / high）> 进程内运行时学到的能力 > 静态规则。
运行时自适应：接口回“不支持关闭思考”（智谱 1210）→ 记为 always、改 low 重试；
回“thinking 参数不支持/无效”类 4xx → 记为 none、去掉 thinking 重试。每次降级写一条 INFO 日志。
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SWITCHABLE, ALWAYS, NONE = "switchable", "always", "none"

# 模型预设上的思考档位（设置 → 模型）；auto = 按能力表。low/high 走 reasoning_effort
THINKING_MODES = {
    "auto": "自动（按模型能力）",
    "disabled": "关闭思考",
    "low": "低（low）",
    "high": "高（high）",
}

_ZHIPU_HOSTS = ("bigmodel.cn", "z.ai")
# (供应商判定, 模型名正则, 能力)；从上到下取第一条命中
# 官方 thinking.type 口径：always=5.3 系列 / 4.7 / 4.5V；switchable=其余 5.x 与 4.5/4.6
_RULES = [
    ("zhipu", re.compile(r"^glm-5\.3", re.I), ALWAYS),
    ("zhipu", re.compile(r"^glm-4\.7(?=-|$)", re.I), ALWAYS),
    ("zhipu", re.compile(r"^glm-4\.5v(?=-|$)", re.I), ALWAYS),
    ("zhipu", re.compile(r"^glm-5", re.I), SWITCHABLE),
    ("zhipu", re.compile(r"^glm-4\.(?:5|6)\b", re.I), SWITCHABLE),
]

# 运行时学到的能力：{(host 标识, 模型名小写): 能力}
_LEARNED: dict = {}


def vendor_of(base_url: str) -> str:
    url = (base_url or "").lower()
    if any(h in url for h in _ZHIPU_HOSTS):
        return "zhipu"
    if "generativelanguage.googleapis.com" in url:
        return "gemini"
    if "deepseek" in url:
        return "deepseek"
    if "volces.com" in url or "ark." in url:
        return "doubao"
    if "openai.com" in url:
        return "openai"
    return "other"


def _key(base_url: str, model: str) -> tuple:
    return vendor_of(base_url), (model or "").strip().lower()


def static_capability(base_url: str, model: str) -> str:
    """静态规则：智谱 always=5.3 系列 / 4.7 / 4.5V；switchable=其余 5.x 与 4.5/4.6；其它供应商/未知不传。"""
    vendor = vendor_of(base_url)
    for v, pattern, cap in _RULES:
        if v == vendor and pattern.match(model or ""):
            return cap
    return NONE


# 单次调用的输出上限（tokens）：(供应商, 模型名正则, 上限)。没列的模型由调用方按保守值处理。
# GLM-5.3 系列：智谱开放文档“核心参数”页，max_tokens 默认 65536、最大 131072，上下文 1M。
# 这里取默认值 65536，不取最大值：拆分镜一块的正文用不到这么多，留出来是给思考用的——
# 始终思考的模型（5.3 系列关不掉思考）把额度吃光时正文会是空的，额度给足才不会空转。
_OUTPUT_CAP_RULES = [
    ("zhipu", re.compile(r"^glm-5\.3", re.I), 65536),
]


def max_output_tokens(base_url: str, model: str) -> Optional[int]:
    """这个模型单次调用最多能输出多少 tokens；不知道返回 None。"""
    vendor = vendor_of(base_url)
    for v, pattern, cap in _OUTPUT_CAP_RULES:
        if v == vendor and pattern.match(model or ""):
            return cap
    return None


def thinking_capability(base_url: str, model: str) -> str:
    return _LEARNED.get(_key(base_url, model)) or static_capability(base_url, model)


THINKING_KEYS = ("thinking", "reasoning_effort")
_LOW = {"reasoning_effort": "low"}


def resolve_thinking(base_url: str, model: str, want: Optional[bool], mode: Optional[str] = None) -> dict:
    """算出要并进请求体的思考字段（{} 表示都不传）。

    want：调用方意图（False=结构化调用不想思考，True=要思考，None=供应商默认不传）。
    mode：模型预设上的手动档位，非 auto 时优先于能力表。
    """
    mode = (mode or "auto").strip().lower()
    learned = _LEARNED.get(_key(base_url, model))
    if mode in ("disabled", "low", "high"):
        if learned == NONE:
            return {}
        if mode == "disabled":
            # 手动选了关闭，但接口已明确不支持关闭：用最低档
            return dict(_LOW) if learned == ALWAYS else {"thinking": {"type": "disabled"}}
        return {"reasoning_effort": mode}
    if want is None:
        return {}
    cap = thinking_capability(base_url, model)
    if cap == SWITCHABLE:
        return {"thinking": {"type": "enabled" if want else "disabled"}}
    if cap == ALWAYS:
        return {} if want else dict(_LOW)
    return {}


def thinks(fragment: dict) -> bool:
    """这组参数下模型还会思考（思考占输出额度）：要给 max_tokens 留余量。"""
    if not fragment:
        return False
    t = (fragment.get("thinking") or {}).get("type")
    return t == "enabled" or fragment.get("reasoning_effort") in ("low", "high", "max")


def supports_thinking_param(base_url: str, model: str) -> bool:
    """按能力表会不会传 thinking（用于放宽结构化调用的输出上限：会思考/可思考的模型输出额度要大一些）。"""
    return thinking_capability(base_url, model) in (SWITCHABLE, ALWAYS)


# ---------------- 运行时自适应 ----------------
_ALWAYS_HINTS = ("不支持关闭思考", "始终思考", "cannot disable thinking", "always think")
_PARAM_HINTS = ("thinking", "思考", "参数")


def is_always_thinking_error(code: str, message: str) -> bool:
    return str(code) == "1210" or any(h in (message or "").lower() for h in _ALWAYS_HINTS)


def is_thinking_param_error(status: int, code: str, message: str) -> bool:
    """4xx 且错误信息指向 thinking/参数：去掉 thinking 重试。"""
    msg = (message or "").lower()
    return 400 <= int(status or 0) < 500 and int(status) != 429 and any(h in msg for h in _PARAM_HINTS)


def next_thinking_after_error(base_url: str, model: str, sent: dict, status: int,
                              code: str, message: str) -> tuple:
    """请求被拒后决定怎么降级。sent 是这次请求里的思考字段。返回 (是否重试, 新的思考字段)。没传思考字段不降级。

    - 回“不支持关闭思考”且当前不是最低档 → 记为 always，改 reasoning_effort=low；
    - 最低档也被拒、或回“thinking 参数不支持/无效” → 记为 none，思考字段都不传。
    """
    if not sent:
        return False, {}
    key = _key(base_url, model)
    cur = json.dumps(sent, ensure_ascii=False)
    reason = f"{status} {code} {message}".strip()
    if is_always_thinking_error(code, message) and sent != _LOW:
        _LEARNED[key] = ALWAYS
        logger.info(f"[模型能力] {model}: {cur} → reasoning_effort=low（原因：{reason}），之后同模型直接用 low")
        return True, dict(_LOW)
    if is_thinking_param_error(status, code, message) or (sent == _LOW and 400 <= int(status) < 500):
        _LEARNED[key] = NONE
        logger.info(f"[模型能力] {model}: {cur} → 不传思考参数（原因：{reason}），之后同模型不传")
        return True, {}
    return False, {}


def forget(base_url: str = None, model: str = None) -> None:
    """清掉运行时学到的能力（测试用；不传参数清全部）。"""
    if base_url is None and model is None:
        _LEARNED.clear()
    else:
        _LEARNED.pop(_key(base_url, model), None)


# ---------------- 结构化长输出（拆分镜 / 一键提取）推荐模型 ----------------
# (供应商, 模型名正则, 推荐改用的模型, 原因)；从上到下取第一条命中。实测见 T-204/T-206：
# glm-4.x-flash（关闭思考）拆分镜常复读到截断或整块只拆 1 段；打开思考则思考吃光输出额度、正文 0 字。
LONG_OUTPUT_ADVICE = [
    ("zhipu", re.compile(r"^glm-4\.\d+-flash$", re.I), "glm-5.3-flashx",
     "拆分镜这类长 JSON 输出常复读到截断或漏段"),
]


def long_output_advice(base_url: str, model: str) -> Optional[dict]:
    """这个模型做拆分镜/一键提取是否不稳：返回 {recommended, reason, message}，稳定的返回 None。"""
    vendor = vendor_of(base_url)
    for v, pattern, recommended, reason in LONG_OUTPUT_ADVICE:
        if v == vendor and pattern.match(model or ""):
            return {"recommended": recommended, "reason": reason,
                    "message": f"{model} {reason}，建议拆分镜用 {recommended}"}
    return None
