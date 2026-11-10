"""替身模式（端到端测试用）

环境变量 DONGAI_FAKE_PROVIDERS=1 时，LLM / 文生图 / TTS / 豆包视频不访问外部服务，
直接返回固定、合法的数据：
- LLM：按提示词类型返回符合解析器预期的内容（小说正文、润色稿、资产提取 JSON、剧本场次 FAKE_SCRIPT_SCENES、
  分镜 JSON：当前模板返回视频段 FAKE_SEGMENTS，旧版模板返回一镜一声 FAKE_SHOTS）
- 文生图：任何模型预设 / 子模型都返回同一张占位图（尺寸由调用方按模型档位算，见 image_provider.image_size）
- 文生图：tests/fixtures/placeholder.png
- TTS：tests/fixtures/speech.mp3
- 视频：tests/fixtures/clip.mp4
- 豆包会员额度：QUOTA_SUMMARY / QUOTA_CARD（标准套餐，16,100 未使用）

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
_JSON_HINTS = (_JSON_SYSTEM_HINT, "只输出一个合法 JSON 对象")

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

# 角色：新格式 face + forms + voice（林风两个形态：第 1 场扫地、第 2 场交手后）；苏婉只有旧字段 description，
# 走旧数据兼容（单形态，穿搭取 description）
FAKE_CHARACTERS = [
    {
        "name": "林风",
        "face": "十七岁少年，清瘦长脸，剑眉星目，眼神隐忍，黑发束成短马尾，肤色偏黄带晒痕，左眉梢一道细小旧疤。",
        "forms": [
            {"name": "场边扫地形态", "outfit": "旧青布短打，腰束麻绳，赤脚踩布鞋，手持扫帚，左手戴一枚青铜古戒，衣摆被雨水打湿。", "scene_nos": [1]},
            {"name": "雨中立威形态", "outfit": "同一身青布短打，衣袖挽到肘上，发梢滴水，麻绳腰带束紧，布鞋沾满泥点，左手青铜古戒泛红光。", "scene_nos": [2]},
        ],
        "voice": "17岁男性，清亮",
        "importance": "main",
        "gender": "male",
        "age_group": "少年",
        "trait": "隐忍",
    },
    {
        "name": "赵虎",
        "face": "二十岁青年，方脸浓眉，嘴角常带轻蔑，短发利落，肤色红润。",
        "forms": [
            {"name": "锦袍形态", "outfit": "墨绿锦袍，金线腰带，黑色长靴，腰间悬玉佩。", "scene_nos": [1, 2]},
        ],
        "voice": "20岁男性，粗犷",
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
        "state_note": "兵器架倾倒、地面积水",
        "views": [
            {"name": "正面视角", "camera": "站在回廊口朝演武场正中"},
            {"name": "高台视角", "camera": "从高台俯视整个演武场"},
        ],
    },
]

# 小说转剧本（SCRIPT_CONVERT_PROMPT 的输出，台词带 kind）：台词/旁白逐字取自 FAKE_NOVEL 与 FAKE_SEGMENTS_COMPACT，
# 基于剧本拆分镜时能按台词反查场次（第 1、2 段在第 1 场，第 3 段在第 2 场）
FAKE_SCRIPT_SCENES = [
    {
        "scene_no": 1,
        "location": "暴雨萧瑟演武场",
        "time": "黄昏外",
        "shot_hint": "全景到中景，暴雨演武场",
        "characters": ["林风", "赵虎", "苏婉"],
        "dialogues": [
            {"speaker": "旁白", "line": "暴雨压在林家演武场上，青石板被砸得白茫茫一片。", "kind": "narration"},
            {"speaker": "旁白", "line": "林风攥着扫帚站在场边，雨水顺着他的发梢往下淌。", "kind": "narration"},
            {"speaker": "旁白", "line": "赵虎踩着积水走过来，停在林风面前。", "kind": "narration"},
            {"speaker": "赵虎", "line": "你也配站在这里？", "kind": "onscreen"},
            {"speaker": "旁白", "line": "林风没有抬头。他左手的青铜古戒忽然发烫，一股热流涌进胸口。", "kind": "narration"},
            {"speaker": "林风", "line": "再忍一忍。", "kind": "inner"},
            {"speaker": "旁白", "line": "苏婉撑着油纸伞站在廊下，眉头紧紧皱起。", "kind": "narration"},
        ],
        "action": "暴雨中林风攥着扫帚立在场边，赵虎踩水逼近，苏婉在廊下撑伞。",
        "beat": "赵虎挑衅，林风隐忍，古戒异动",
        "summary": "赵虎当众羞辱林风",
    },
    {
        "scene_no": 2,
        "location": "演武场中央",
        "time": "黄昏外",
        "characters": ["林风", "赵虎"],
        "dialogues": [
            {"speaker": "旁白", "line": "赵虎抬手就是一掌。林风侧身一让，扫帚柄正点在赵虎手腕上。", "kind": "narration"},
            {"speaker": "旁白", "line": "赵虎捂着手腕连退三步，脸色铁青。", "kind": "narration"},
            {"speaker": "林风", "line": "三个月后的族比，我等你。", "kind": "onscreen"},
        ],
        "action": "赵虎挥掌，林风侧身闪开，扫帚柄点中赵虎手腕，转身走进雨里。",
        "beat": "反击立威，留下族比之约",
        "summary": "林风一招逼退赵虎",
    },
]

# 视频段格式（当前拆分镜模板的输出）：一条 = 一次 15 秒视频生成
FAKE_SEGMENTS = [
    {
        "segment_no": 1,
        "duration": 15,
        "scene": "暴雨萧瑟演武场，黄昏暴雨，压抑",
        "mood": "压抑",
        "characters": ["林风", "赵虎"],
        "props": [],
        "positions": "林风在画面中央偏左站在场边，赵虎从右侧远处走近",
        "continuity": "开场",
        "lines": [
            {"speaker": "旁白", "text": "暴雨压在林家演武场上，青石板被砸得白茫茫一片。", "kind": "narration", "start": 0.5, "end": 5.4},
            {"speaker": "旁白", "text": "林风攥着扫帚站在场边，雨水顺着他的发梢往下淌。", "kind": "narration", "start": 5.8, "end": 10.5},
            {"speaker": "旁白", "text": "赵虎踩着积水走过来，停在林风面前。", "kind": "narration", "start": 10.9, "end": 14.2},
        ],
        "beats": [
            {"start": 0, "end": 5.5, "shot_size": "全景", "camera": "高位俯拍", "move": "缓慢推近", "action": "暴雨中的演武场，林风独自立在场边", "line_refs": [1]},
            {"start": 5.5, "end": 10.7, "shot_size": "近景", "camera": "平视", "move": "固定", "action": "雨水顺着林风发梢滴落，他攥紧扫帚", "line_refs": [2]},
            {"start": 10.7, "end": 15, "shot_size": "中景", "camera": "低角度", "move": "跟拍", "action": "赵虎踩着积水走近，停在林风面前", "line_refs": [3]},
        ],
        "video_prompt": "开场镜头，直接建立时间地点人物；角色：林风＝男少年、青布短打、隐忍，赵虎＝男青年、墨绿锦袍、轻蔑；场景基调与站位：黄昏暴雨，冷灰色调，林风在中央偏左，赵虎从右侧走近，机位不越轴；[0-5.5秒]全景，高位俯拍，缓慢推近，林风独自立在雨中（画外音，画面人物不张嘴）；音效：密集雨声；[5.5-10.7秒]近景，平视，固定，雨水顺着林风发梢滴落，他攥紧扫帚；音效：雨滴打在扫帚柄上；[10.7-15秒]中景，低角度，跟拍，赵虎踩着积水走近，停在林风面前；音效：脚步踏水声；画面中人物不开口说话；尾态：两人相对而立",
        "tail": "两人相对而立",
        "image_prompt": "黄昏暴雨中的青石板演武场，少年持扫帚立于场边，全景，冷色调",
        "neg_prompt": "文字，水印，肢体畸形",
    },
    {
        "segment_no": 2,
        "duration": 15,
        "scene": "暴雨萧瑟演武场，雨幕中，对峙",
        "mood": "紧张",
        "characters": ["赵虎", "林风", "苏婉"],
        "props": ["青铜古戒"],
        "positions": "赵虎在画面左侧面朝右，林风在右侧三步外，苏婉在后景廊下",
        "continuity": "承接上一段：两人相对而立",
        "lines": [
            {"speaker": "赵虎", "text": "你也配站在这里？", "kind": "onscreen", "start": 0.5, "end": 2.1},
            {"speaker": "旁白", "text": "林风没有抬头。他左手的青铜古戒忽然发烫，一股热流涌进胸口。", "kind": "narration", "start": 2.6, "end": 8.4},
            {"speaker": "林风", "text": "再忍一忍。", "kind": "inner", "start": 8.8, "end": 9.9},
            {"speaker": "旁白", "text": "苏婉撑着油纸伞站在廊下，眉头紧紧皱起。", "kind": "narration", "start": 10.3, "end": 13.9},
        ],
        "beats": [
            {"start": 0, "end": 2.4, "shot_size": "中近景", "camera": "过肩", "move": "固定", "action": "赵虎冷笑俯视林风", "line_refs": [1]},
            {"start": 2.4, "end": 8.6, "shot_size": "特写", "camera": "平视", "move": "缓慢推近", "action": "林风左手青铜古戒泛起暗红微光", "line_refs": [2]},
            {"start": 8.6, "end": 10.1, "shot_size": "近景", "camera": "侧光", "move": "固定", "action": "林风闭口垂眼，下颌绷紧", "line_refs": [3]},
            {"start": 10.1, "end": 15, "shot_size": "远景", "camera": "前景廊柱遮挡", "move": "横移", "action": "苏婉在廊下撑伞皱眉", "line_refs": [4]},
        ],
        "video_prompt": "承接上一段：两人相对而立；角色：赵虎＝男青年、墨绿锦袍、轻蔑，林风＝男少年、布衣、隐忍，苏婉＝女青年、月白襦裙、关切；场景与站位：暴雨萧瑟演武场，赵虎在左，林风在右，苏婉在后景廊下；[0-2.4秒]中近景，过肩，固定，赵虎正面露脸，赵虎（冷笑）说：你也配站在这里？林风只低头不语；音效：雨声；[2.4-8.6秒]特写，平视，缓慢推近，林风左手青铜古戒泛起暗红微光（画外音，画面人物不张嘴）；音效：低沉嗡鸣；[8.6-10.1秒]近景，侧光，固定，（画外音，画面人物不张嘴）林风垂眼，下颌绷紧；[10.1-15秒]远景，前景廊柱遮挡，横移，苏婉在廊下撑伞，指尖捏紧伞柄（画外音，画面人物不张嘴）；音效：雨打油纸伞；尾态：赵虎抬手",
        "tail": "赵虎抬手",
        "image_prompt": "锦袍青年冷笑俯视布衣少年，雨中过肩中近景",
        "neg_prompt": "文字，水印，面部崩坏",
    },
    {
        "segment_no": 3,
        "duration": 15,
        "scene": "暴雨萧瑟演武场，雨夜，反转",
        "mood": "爽快",
        "characters": ["林风", "赵虎"],
        "props": ["青铜古戒"],
        "positions": "林风在画面中央，赵虎在左侧连退，围观族人在后景",
        "continuity": "承接上一段：赵虎抬手",
        "lines": [
            {"speaker": "旁白", "text": "赵虎抬手就是一掌。林风侧身一让，扫帚柄正点在赵虎手腕上。", "kind": "narration", "start": 0.5, "end": 6.1},
            {"speaker": "旁白", "text": "赵虎捂着手腕连退三步，脸色铁青。", "kind": "narration", "start": 6.5, "end": 9.6},
            {"speaker": "林风", "text": "三个月后的族比，我等你。", "kind": "onscreen", "start": 10.2, "end": 12.6},
        ],
        "beats": [
            {"start": 0, "end": 3.2, "shot_size": "中景", "camera": "侧面", "move": "快速横移", "action": "赵虎挥掌，林风侧身闪开", "line_refs": [1]},
            {"start": 3.2, "end": 6.3, "shot_size": "特写", "camera": "平视", "move": "慢动作", "action": "扫帚柄点中赵虎手腕，雨水四溅", "line_refs": []},
            {"start": 6.3, "end": 10, "shot_size": "中景", "camera": "仰拍", "move": "固定", "action": "赵虎捂着手腕连退三步", "line_refs": [2]},
            {"start": 10, "end": 15, "shot_size": "近景", "camera": "正面", "move": "缓慢拉远", "action": "林风正面露脸，平静开口后转身走进雨里", "line_refs": [3]},
        ],
        "video_prompt": "承接上一段：赵虎抬手；角色：林风＝男少年、布衣、坚定，赵虎＝男青年、锦袍、震惊；场景与站位：暴雨萧瑟演武场，林风在中央，赵虎在左；[0-3.2秒]中景，侧面，快速横移，赵虎挥掌，林风侧身闪开（画外音，画面人物不张嘴）；音效：衣袂破风声；[3.2-6.3秒]特写，平视，慢动作，扫帚柄点中赵虎手腕，雨水四溅；音效：竹柄击打声；[6.3-10秒]中景，仰拍，固定，赵虎捂着手腕连退三步（画外音，画面人物不张嘴）；音效：脚步踏水声；[10-15秒]近景，正面，缓慢拉远，林风正面露脸，林风（平静）说：三个月后的族比，我等你。说完转身走进雨里；音效：雨声；尾态：林风走进雨里",
        "tail": "林风走进雨里",
        "image_prompt": "少年左手青铜古戒泛起暗红微光，雨中特写",
        "neg_prompt": "文字，水印",
    },
]

# 当前拆分镜模板的紧凑输出（模型只写 scene/pos/mood/sound/lines/beats，其余由代码补）；内容与 FAKE_SEGMENTS 一致
FAKE_SEGMENTS_COMPACT = [
    {
        "scene": "暴雨萧瑟演武场，黄昏暴雨，压抑",
        "pos": "林风在画面中央偏左站在场边，赵虎从右侧远处走近",
        "mood": "压抑",
        "sound": "密集雨声，脚步踏水",
        "lines": ["旁白：暴雨压在林家演武场上，青石板被砸得白茫茫一片。",
                  "旁白：林风攥着扫帚站在场边，雨水顺着他的发梢往下淌。",
                  "旁白：赵虎踩着积水走过来，停在林风面前。"],
        "beats": ["全景|高位俯拍|缓慢推近|暴雨中的演武场，林风独自立在场边|无|1",
                  "近景|平视|固定|雨水顺着林风发梢滴落，他五指攥紧扫帚|下颌绷紧，眼眶泛红却咬唇|2",
                  "中景|低角度|跟拍|赵虎踩着积水走近，停在林风面前|嘴角一撇|3"],
    },
    {
        "scene": "暴雨萧瑟演武场，雨幕中，对峙",
        "pos": "赵虎在画面左侧面朝右，林风在右侧三步外，苏婉在后景廊下",
        "mood": "紧张",
        "sound": "雨声，雨打油纸伞",
        "lines": ["赵虎：你也配站在这里？",
                  "旁白：林风没有抬头。他左手的青铜古戒忽然发烫，一股热流涌进胸口。",
                  "林风（心声）：再忍一忍。",
                  "旁白：苏婉撑着油纸伞站在廊下，眉头紧紧皱起。"],
        "beats": ["中近景|过肩|固定|赵虎俯身逼近，俯视林风|冷笑|1",
                  "特写|平视|缓慢推近|林风左手青铜古戒泛起暗红微光|无|2",
                  "近景|侧光|固定|林风闭口垂眼|下颌绷紧，喉结滚动|3",
                  "远景|前景廊柱遮挡|横移|苏婉在廊下撑伞，指尖捏紧伞柄|眉头紧皱|4"],
    },
    {
        "scene": "暴雨萧瑟演武场，雨夜，反转",
        "pos": "林风在画面中央，赵虎在左侧连退，围观族人在后景",
        "mood": "爽快",
        "sound": "衣袂破风，竹柄击打",
        "lines": ["旁白：赵虎抬手就是一掌。林风侧身一让，扫帚柄正点在赵虎手腕上。",
                  "旁白：赵虎捂着手腕连退三步，脸色铁青。",
                  "林风：三个月后的族比，我等你。"],
        "beats": ["中景|侧面|快速横移|赵虎挥掌，林风侧身闪开|无|1",
                  "特写|平视|慢动作|扫帚柄点中赵虎手腕，雨水四溅|无|",
                  "中景|仰拍|固定|赵虎捂着手腕连退三步|脸色铁青，嘴唇发抖|2",
                  "近景|正面|缓慢拉远|林风正面露脸，青铜古戒微光一闪，转身走进雨里|平静，眼神笃定|3"],
    },
]

# 小说里带这个标记时，替身模拟“输出达到 max_tokens 被截断”（finish_reason=length），用来测截断路径
TRUNCATE_MARKER = "【替身截断】"

# 旧格式（一镜一声）：用户自定义的旧版拆分镜模板仍会产出它，用来测兼容
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


# 豆包额度接口的替身响应（结构同真实接口，只保留规范化用到的字段）
QUOTA_SUMMARY = {
    "code": 0,
    "data": {
        "current_subscription": {"display": {"short_name": "标准套餐"}},
        "member_info": {"hasActiveSubscription": True},
        "window_limit_section": {
            "entitlement_count": 2,
            "usage_exhausted": False,
            "window_limit_groups": [{
                "feature_group": "general",
                "should_prompt_purchase": False,
                "window_limits": [{"total_amount": "16,100", "used_amount": "0", "used_percent": 0,
                                   "less_than_one_percent": False, "window_type": 2,
                                   "start_time": 0, "end_time": 0, "item_type": 0}],
            }],
        },
    },
}
QUOTA_CARD = {"code": 0, "data": {"available_count": 0}}


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
    # chat_json 只在首条不是 system 时才补 _JSON_SYSTEM_HINT；prompt_registry 的消息自带契约（“只输出一个合法 JSON 对象”）
    return any(m.get("role") == "system" and any(h in str(m.get("content") or "") for h in _JSON_HINTS)
               for m in messages or [])


def _polished(prompt: str) -> str:
    m = re.search(r"【小说原文】\s*(.*?)\s*【人称】", prompt, re.S)
    source = (m.group(1) if m else "").strip() or FAKE_NOVEL.strip()
    return "（润色稿）" + source


def llm_reply(messages: list) -> str:
    """按提示词类型返回固定内容；结构化调用返回 JSON 文本。"""
    prompt = _last_user_text(messages)
    if _is_json_call(messages):
        # JSON 结构示例在 system 契约里（prompt_registry），按类型判断要看全部消息，不只最后一条 user
        prompt = "\n".join(str(m.get("content") or "") for m in messages or [])
        if '"segments"' in prompt:
            if TRUNCATE_MARKER in prompt:
                return json.dumps({"segments": FAKE_SEGMENTS_COMPACT}, ensure_ascii=False)[:120]
            data = {"segments": FAKE_SEGMENTS_COMPACT}
        elif '"shots"' in prompt:
            data = {"shots": FAKE_SHOTS}
        elif '"dialogues"' in prompt:
            data = {"scenes": FAKE_SCRIPT_SCENES}
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


def finish_reason(messages: list) -> str:
    """流式结束原因：小说里带截断标记时返回 length，其余 stop。"""
    return "length" if _is_json_call(messages) and TRUNCATE_MARKER in _last_user_text(messages) else "stop"


def chunks(text: str, size: int = 40):
    """把整段文本切成小块，模拟流式输出"""
    for i in range(0, len(text), size):
        yield text[i:i + size]
