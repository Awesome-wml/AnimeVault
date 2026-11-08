"""替身模式（端到端测试用）

环境变量 DONGAI_FAKE_PROVIDERS=1 时，LLM / 文生图 / TTS / 豆包视频不访问外部服务，
直接返回固定、合法的数据：
- LLM：按提示词类型返回符合解析器预期的内容（小说正文、润色稿、资产提取 JSON、分镜 JSON）
- 文生图：tests/fixtures/placeholder.png
- TTS：tests/fixtures/speech.mp3
- 视频：tests/fixtures/clip.mp4

各 provider 只在入口处判断一次 enabled()；开关关闭时原有代码路径完全不变。
素材目录可用 DONGAI_FAKE_FIXTURES 覆盖。
"""
import json
import os
import re
from pathlib import Path

_DEFAULT_FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"

# 与 core/providers/llm_provider.py chat_json 注入的系统提示一致，用来识别结构化调用
_JSON_SYSTEM_HINT = "严格按照要求的JSON格式输出"

FAKE_NOVEL = """暴雨演武场

暴雨压在林家演武场上，青石板被砸得白茫茫一片。林风攥着扫帚站在场边，雨水顺着他的发梢往下淌。

赵虎踩着积水走过来，锦袍下摆溅满泥点。他停在林风面前，冷笑一声。

“你也配站在这里？”

林风没有抬头。他左手的青铜古戒忽然发烫，一股热流顺着手臂涌进胸口。

苏婉撑着油纸伞站在廊下，远远看着这一幕，眉头紧紧皱起。

赵虎抬手就是一掌。林风侧身一让，扫帚柄在雨里划出一道弧线，正点在赵虎手腕上。

围观的族人一片哗然。赵虎捂着手腕连退三步，脸色铁青。

“三个月后的族比，我等你。”林风把扫帚往地上一顿，转身走进雨里。
"""

FAKE_CHARACTERS = [
    {
        "name": "林风",
        "description": "十七岁少年，清瘦挺拔；剑眉星目，眼神隐忍；身形单薄但站姿笔直；旧青布短打，腰束麻绳，赤脚踩布鞋；左手戴一枚青铜古戒。",
        "importance": "main",
        "gender": "male",
        "age_group": "少年",
        "trait": "隐忍",
    },
    {
        "name": "赵虎",
        "description": "二十岁青年，身材魁梧；方脸浓眉，嘴角常带轻蔑；肩宽背厚；墨绿锦袍，金线腰带，黑色长靴。",
        "importance": "support",
        "gender": "male",
        "age_group": "青年",
        "trait": "跋扈",
    },
    {
        "name": "苏婉",
        "description": "十八岁少女，身段纤细；柳眉杏眼，神情关切；月白襦裙，外披浅青纱衣，发间一支白玉簪，手持油纸伞。",
        "importance": "support",
        "gender": "female",
        "age_group": "青年",
        "trait": "温柔",
    },
]

FAKE_PROPS = [
    {
        "name": "青铜古戒",
        "prop_type": "信物",
        "description": "指环宽约一指，青铜质地布满暗绿铜锈，戒面刻着细密云雷纹，遇到灵气会发出暗红微光并微微发烫。",
    },
]

FAKE_SCENES = [
    {
        "name": "暴雨萧瑟演武场",
        "scene_type": "室外",
        "description": "宽阔的青石板演武场，四周是木质回廊和兵器架；黄昏暴雨，天色铁灰，雨幕密集；氛围压抑肃杀；地面积水反光，前景兵器架，远景飞檐屋脊。",
    },
]

FAKE_SHOTS = [
    {
        "shot_no": 1,
        "character_name": "旁白",
        "text": "暴雨压在林家演武场上，青石板被砸得白茫茫一片。",
        "duration": 4,
        "scene": "暴雨萧瑟演武场，黄昏暴雨，压抑",
        "positions": "林风在画面中央偏左，独自站在场边",
        "characters": ["林风"],
        "props": [],
        "camera": "全景缓慢推近",
        "prompt": "黄昏暴雨中的青石板演武场，少年持扫帚立于场边，全景，冷色调",
        "video_prompt": "开场镜头，直接建立时间地点人物；角色：林风＝男少年、青布短打、隐忍；场景与站位：暴雨萧瑟演武场，林风在中央偏左；[0-4秒]全景，平视，缓慢推近，林风握着扫帚一动不动；旁白（低沉）：暴雨压在林家演武场上，青石板被砸得白茫茫一片。音效：密集雨声；尾态：林风低头站立；约束：无字幕、无水印、无logo、无背景音乐，人物前后一致，肢体正常",
        "neg_prompt": "文字，水印，肢体畸形",
    },
    {
        "shot_no": 2,
        "character_name": "赵虎",
        "text": "你也配站在这里？",
        "duration": 3,
        "scene": "暴雨萧瑟演武场，雨幕中",
        "positions": "赵虎在画面左侧面朝右，林风在右侧三步外",
        "characters": ["赵虎", "林风"],
        "props": [],
        "camera": "中近景过肩",
        "prompt": "锦袍青年冷笑俯视布衣少年，雨中过肩中近景",
        "video_prompt": "承接上一镜：林风低头站立；角色：赵虎＝男青年、墨绿锦袍、轻蔑，林风＝男少年、布衣、隐忍；场景与站位：暴雨萧瑟演武场，赵虎在左，林风在右；[0-3秒]中近景，过肩，固定，赵虎（冷笑）说：你也配站在这里？音效：雨声，脚步踏水声；尾态：林风握紧扫帚；约束：无字幕、无水印、无logo、无背景音乐，人物前后一致，肢体正常",
        "neg_prompt": "文字，水印，面部崩坏",
    },
    {
        "shot_no": 3,
        "character_name": "林风",
        "text": "三个月后的族比，我等你。",
        "duration": 3,
        "scene": "暴雨萧瑟演武场，雨夜",
        "positions": "林风在画面中央转身，赵虎在后景",
        "characters": ["林风", "赵虎"],
        "props": ["青铜古戒"],
        "camera": "特写拉远",
        "prompt": "少年左手青铜古戒泛起暗红微光，雨中特写",
        "video_prompt": "承接上一镜：林风握紧扫帚；角色：林风＝男少年、布衣、坚定；场景与站位：暴雨萧瑟演武场，林风在中央；[0-3秒]特写，平视，缓慢拉远，林风（平静）说：三个月后的族比，我等你。音效：雨滴打在瓦檐；尾态：林风走进雨里；约束：无字幕、无水印、无logo、无背景音乐，人物前后一致，肢体正常",
        "neg_prompt": "文字，水印",
    },
]


def enabled() -> bool:
    return os.environ.get("DONGAI_FAKE_PROVIDERS", "").strip().lower() in ("1", "true", "yes", "on")


def fixtures_dir() -> Path:
    custom = os.environ.get("DONGAI_FAKE_FIXTURES")
    return Path(custom) if custom else _DEFAULT_FIXTURES


def _read(name: str) -> bytes:
    return (fixtures_dir() / name).read_bytes()


def image_bytes() -> bytes:
    return _read("placeholder.png")


def speech_bytes() -> bytes:
    return _read("speech.mp3")


def video_bytes() -> bytes:
    return _read("clip.mp4")


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _is_json_call(messages: list) -> bool:
    return any(m.get("role") == "system" and _JSON_SYSTEM_HINT in str(m.get("content") or "")
               for m in messages or [])


def _polished(prompt: str) -> str:
    m = re.search(r"【小说原文】\s*(.*?)\s*【人称】", prompt, re.S)
    source = (m.group(1) if m else "").strip() or FAKE_NOVEL.strip()
    return "（润色稿）" + source


def llm_reply(messages: list) -> str:
    """按提示词类型返回固定内容；结构化调用返回 JSON 文本。"""
    prompt = _last_user_text(messages)
    if _is_json_call(messages):
        if '"shots"' in prompt:
            data = {"shots": FAKE_SHOTS}
        elif '"characters"' in prompt and '"props"' in prompt and '"scenes"' in prompt:
            data = {"characters": FAKE_CHARACTERS, "props": FAKE_PROPS, "scenes": FAKE_SCENES}
        elif '"characters"' in prompt:
            data = {"characters": FAKE_CHARACTERS}
        elif '"props"' in prompt:
            data = {"props": FAKE_PROPS}
        elif '"scenes"' in prompt:
            data = {"scenes": FAKE_SCENES}
        else:
            data = {}
        return json.dumps(data, ensure_ascii=False)
    if "【小说原文】" in prompt:
        return _polished(prompt)
    return FAKE_NOVEL


def chunks(text: str, size: int = 40):
    """把整段文本切成小块，模拟流式输出"""
    for i in range(0, len(text), size):
        yield text[i:i + size]
