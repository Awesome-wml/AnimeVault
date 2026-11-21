from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId


# ============= 通用模型 =============
class PyObjectId(ObjectId):
    """MongoDB ObjectId适配器"""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)
    
    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        schema.update(type="string")
        return schema


# ============= 用户模块 =============
class UserRegister(BaseModel):
    """用户注册"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserConfig(BaseModel):
    """用户配置（LLM API密钥）"""
    doubao_api_key: Optional[str] = None
    doubao_base_url: Optional[str] = "https://open.bigmodel.cn/api/paas/v4"
    doubao_model: Optional[str] = "glm-4.5-flash"


class UserInfo(BaseModel):
    """用户信息"""
    id: str
    username: str
    has_api_key: bool
    doubao_base_url: Optional[str] = None
    doubao_model: Optional[str] = None
    create_time: datetime


# ============= 项目模块 =============
class ProjectCreate(BaseModel):
    """创建项目"""
    name: str = Field(..., min_length=1, max_length=200)
    genre: Optional[str] = None  # 题材（core/style_library.GENRES 的 genre 键，也可自由文本）
    medium: Optional[str] = None  # 媒介 id（真人实拍 / 3D 国漫 / 2D 子风格）
    style: Optional[str] = None  # 旧风格 id，兼容保留
    # "auto"：不手选风格，贴入小说后由 AI 识别（core/style_suggest.py）；不传时按是否给了 medium/genre 判断
    style_source: Optional[str] = None


class ProjectUpdate(BaseModel):
    """更新项目"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    novel_content: Optional[str] = None
    genre: Optional[str] = None
    medium: Optional[str] = None
    style: Optional[str] = None
    video_model: Optional[str] = None  # 视频模型 key（core/video_models.py），默认 Seedance 2.0 Fast
    script_person: Optional[str] = None  # 转剧本旁白人称：first / third / keep
    script_target_seconds: Optional[int] = Field(None, ge=0, le=3600)  # 转剧本目标时长（秒），0 = 清空（按原文三成）
    narrator_voice: Optional[str] = Field(None, max_length=30)  # 旁白的声音，如“沉稳青年男声”；空串 = 恢复缺省
    style_source: Optional[str] = None  # 改 medium/genre 时默认记为 user（手动确认，不再自动覆盖）


class ProjectInfo(BaseModel):
    """项目信息"""
    id: str
    user_id: str
    name: str
    novel_content: Optional[str] = None
    genre: Optional[str] = None
    medium: Optional[str] = None
    style: Optional[str] = None
    video_model: Optional[str] = None
    script_person: Optional[str] = None
    script_target_seconds: Optional[int] = None
    narrator_voice: Optional[str] = None   # 旁白的声音（没设过返回缺省）
    style_source: Optional[str] = None   # auto 待识别 / ai 已识别 / user 手动选择（老作品为空）
    style_reason: Optional[str] = None   # AI 识别的理由
    create_time: datetime


# ============= 小说生成 =============
class NovelGenerate(BaseModel):
    """小说生成请求"""
    project_id: str
    video_set_id: Optional[str] = None  # 归属集数；空则取项目第一集
    genre: str = Field(..., description="题材，如：都市、玄幻、古风")
    style: str = Field(..., description="风格，如：轻松搞笑、悬疑烧脑")
    outline: str = Field(..., description="故事梗概")
    protagonist: str = Field(..., description="主角设定")
    target_words: int = Field(default=5000, ge=1000, le=50000, description="目标字数")
    model_id: Optional[str] = None   # 模型预设ID，空则用全局默认
    model: Optional[str] = None      # 指定具体模型，覆盖预设默认模型
    prompt_id: str = Field(default="", description="指定提示词ID，空则用默认")


class NovelPolish(BaseModel):
    """小说润色/改编为漫剧文本"""
    project_id: str
    text: str = Field(..., description="待润色的小说原文")
    model_id: Optional[str] = None   # 模型预设ID，空则用全局默认
    model: Optional[str] = None      # 指定具体模型，覆盖预设默认模型
    prompt_id: Optional[str] = None  # 提示词ID，空则用 novel_polish 类型默认
    person: Optional[str] = None     # first 第一人称 / third 第三人称 / 空=保持原文


# ============= 角色模块 =============
class CharacterForm(BaseModel):
    """角色的一个形态：穿搭 + 出现场次 + 该形态的三视图（见 core/character_forms.py）"""
    name: Optional[str] = None
    outfit: Optional[str] = None
    scene_nos: Optional[List[int]] = None   # 剧本按【场次N】，小说按段落序号
    image_path: Optional[str] = None


class CharacterCreate(BaseModel):
    """创建角色"""
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    face: Optional[str] = None            # 核心固定面部特征（不含服装）
    forms: Optional[List[CharacterForm]] = None
    voice: Optional[str] = None           # 音色描述：年龄+性别+声音属性
    voice_design: Optional[dict] = None   # 声音设定 {pitch, timbre, pace, manner, habit}（core/voice_design）
    voice_name: Optional[str] = None
    importance: Optional[str] = None  # main核心 / support配角 / extra路人
    gender: Optional[str] = None      # male/female
    age_group: Optional[str] = None   # 少年/青年/中年/暮年
    trait: Optional[str] = None       # 特质：阳刚/阴森/温柔/阳光/威严...


class CharacterUpdate(BaseModel):
    """更新角色"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    face: Optional[str] = None
    forms: Optional[List[CharacterForm]] = None   # 整体替换；没带 image_path 的形态按下标沿用原图
    voice: Optional[str] = None
    voice_design: Optional[dict] = None   # 手改声音设定（整体替换，记为用户设定，之后 AI 设计不覆盖）；{} 清空
    voice_name: Optional[str] = None
    image_path: Optional[str] = None
    importance: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    trait: Optional[str] = None


class VoiceDesignRequest(BaseModel):
    """AI 设计音色：给作品的全体角色定声音"""
    project_id: str
    model_id: Optional[str] = None
    model: Optional[str] = None
    overwrite: bool = False               # True：AI 设计过的也重做（手改过的始终不动）


class CharacterInfo(BaseModel):
    """角色信息"""
    id: str
    user_id: str
    project_id: str
    name: str
    description: Optional[str] = None
    face: Optional[str] = None
    forms: List[CharacterForm] = []   # 至少 1 个；旧数据返回单形态（穿搭 = description，图 = image_path）
    voice: Optional[str] = None
    voice_design: Optional[dict] = None
    voice_design_source: Optional[str] = None   # ai 模型设计 / rule 按年龄气质推的 / user 手改
    voice_line: Optional[str] = None            # 写进视频提示词的那一句（每段相同）
    voice_name: Optional[str] = None
    image_path: Optional[str] = None   # 第一形态的三视图
    importance: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    trait: Optional[str] = None


class CharacterExtract(BaseModel):
    """AI提取角色"""
    project_id: str
    novel_text: str
    medium: Optional[str] = None  # 媒介 id，可选
    genre: Optional[str] = None  # 题材，可选
    style: Optional[str] = None  # 旧风格ID，兼容保留
    model_id: Optional[str] = None  # 模型预设ID，空则用全局默认
    prompt_id: Optional[str] = None  # 提示词ID，空则用类型默认
    model: Optional[str] = None  # 指定具体模型ID，覆盖预设默认模型


# ============= 道具模块 =============
class PropCreate(BaseModel):
    """创建道具"""
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    prop_type: Optional[str] = None  # 道具类型，如：武器、法宝、信物
    description: Optional[str] = None
    image_path: Optional[str] = None


class PropUpdate(BaseModel):
    """更新道具"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    prop_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None


class PropInfo(BaseModel):
    """道具信息"""
    id: str
    user_id: str
    project_id: str
    name: str
    prop_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None


class PropExtract(BaseModel):
    """AI提取道具"""
    project_id: str
    novel_text: str
    medium: Optional[str] = None
    genre: Optional[str] = None
    style: Optional[str] = None  # 旧风格ID，兼容保留
    model_id: Optional[str] = None
    prompt_id: Optional[str] = None
    model: Optional[str] = None


# ============= 场景模块 =============
class SceneCreate(BaseModel):
    """创建场景"""
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    scene_type: Optional[str] = None  # 场景类型，如：室内、室外、宫殿
    description: Optional[str] = None
    image_path: Optional[str] = None
    state_note: Optional[str] = None  # 剧情发生时关键物件状态（≤40 字）
    views: Optional[List[dict]] = None  # 视角 [{name, camera, image_path}]


class SceneUpdate(BaseModel):
    """更新场景"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    scene_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None
    state_note: Optional[str] = None
    views: Optional[List[dict]] = None


class SceneInfo(BaseModel):
    """场景信息"""
    id: str
    user_id: str
    project_id: str
    name: str
    scene_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None
    state_note: Optional[str] = None
    views: List[dict] = []  # 旧数据也返回单视角


class SceneExtract(BaseModel):
    """AI提取场景"""
    project_id: str
    novel_text: str
    medium: Optional[str] = None
    genre: Optional[str] = None
    style: Optional[str] = None  # 旧风格ID，兼容保留
    model_id: Optional[str] = None
    prompt_id: Optional[str] = None
    model: Optional[str] = None


class AssetExtract(BaseModel):
    """AI全量提取：一次调用同时提取角色/道具/场景"""
    project_id: str
    video_set_id: Optional[str] = None
    novel_text: str
    medium: Optional[str] = None
    genre: Optional[str] = None
    style: Optional[str] = None  # 旧风格ID，兼容保留
    model_id: Optional[str] = None
    prompt_id: Optional[str] = None
    model: Optional[str] = None


# ============= 分镜模块 =============
class ShotCreate(BaseModel):
    """创建分镜"""
    project_id: str
    shot_no: int
    scene_no: Optional[int] = None
    text: str
    prompt: Optional[str] = None
    neg_prompt: Optional[str] = None
    duration: float = Field(default=15.0, ge=0.5, le=30.0)
    character_name: Optional[str] = None  # 说话角色名，旁白填"旁白"


class ShotUpdate(BaseModel):
    """更新分镜"""
    shot_no: Optional[int] = None
    text: Optional[str] = None
    prompt: Optional[str] = None
    neg_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    video_path: Optional[str] = None
    img_path: Optional[str] = None
    character_name: Optional[str] = None
    camera: Optional[str] = None
    duration: Optional[float] = Field(default=None, ge=0.5, le=30.0)
    scene: Optional[str] = None          # 场景描述
    positions: Optional[str] = None      # 人物站位
    characters: Optional[List[str]] = None  # 本单元出场角色（资产名）
    props: Optional[List[str]] = None       # 本单元出现的道具（资产名）
    forms: Optional[dict] = None            # 这一段各角色用哪个形态 {角色名: 形态名}；{} 清空
    # 视频段（一条 = 一次视频生成）
    lines: Optional[List[dict]] = None      # 逐句台词 [{speaker, text, kind, start, end}]
    beats: Optional[List[dict]] = None      # 段内小镜头 [{start, end, shot_size, camera, move, action, line_refs}]
    mood: Optional[str] = None
    continuity: Optional[str] = None
    tail: Optional[str] = None
    storyboard_prompt: Optional[str] = None  # 四格分镜文案（代码从小镜头拼，可手改；改小镜头后自动重拼）
    storyboard_path: Optional[str] = None


class ShotInfo(BaseModel):
    """分镜信息"""
    model_config = ConfigDict(protected_namespaces=())
    id: str
    project_id: str
    shot_no: int
    scene_no: Optional[int] = None
    text: str
    prompt: Optional[str] = None
    neg_prompt: Optional[str] = None
    camera: Optional[str] = None
    duration: Optional[float] = None
    video_prompt: Optional[str] = None
    scene: Optional[str] = None
    positions: Optional[str] = None
    characters: Optional[List[str]] = None
    props: Optional[List[str]] = None
    forms: Optional[dict] = None            # 这一段各角色用哪个形态 {角色名: 形态名}（拆分镜时按规划定，可手改）
    video_path: Optional[str] = None
    img_path: Optional[str] = None
    audio_path: Optional[str] = None
    character_name: Optional[str] = None
    # 视频段字段；旧数据（一镜一声）为空
    lines: Optional[List[dict]] = None
    beats: Optional[List[dict]] = None
    mood: Optional[str] = None
    model_key: Optional[str] = None
    continuity: Optional[str] = None
    tail: Optional[str] = None
    speech_seconds: Optional[float] = None   # 本段台词朗读总时长（秒）
    fill_rate: Optional[float] = None        # 填充率 = 朗读时长 / 段时长
    # 四格分镜图（视频参考图）：图、四格文案、四格与小镜头/时间段的对应（[{panel, pos, start, end, text}]）
    storyboard_path: Optional[str] = None
    storyboard_prompt: Optional[str] = None
    storyboard_panels: Optional[List[dict]] = None


class ShotSplit(BaseModel):
    """AI拆分分镜"""
    project_id: str
    novel_paragraph: str
    model_id: Optional[str] = None
    prompt_id: Optional[str] = None
    model: Optional[str] = None
    video_set_id: Optional[str] = None


# ============= 剧本模块 =============
class ScriptDialogue(BaseModel):
    """场次对白。kind：narration 旁白 / inner 心声 / onscreen 当面说 / offscreen 画外音（缺省按说话人推断）"""
    speaker: str
    line: str
    kind: Optional[str] = None


class ScriptConvert(BaseModel):
    """小说转剧本请求。person / target_seconds 不传时用项目设置（script_person / script_target_seconds）"""
    project_id: str
    video_set_id: Optional[str] = None  # 归属集数；空则取项目第一集
    novel_text: str
    model_id: Optional[str] = None
    prompt_id: Optional[str] = None
    model: Optional[str] = None
    person: Optional[str] = None  # first / third / keep（默认 keep：沿用原文人称）
    target_seconds: Optional[int] = Field(None, ge=0, le=3600)  # 目标时长（秒）；空或 0 = 台词约为原文三成


class ScriptInfo(BaseModel):
    """剧本场次"""
    id: str
    project_id: str
    video_set_id: Optional[str] = None
    scene_no: int
    location: Optional[str] = None
    time: Optional[str] = None
    characters: List[str] = []
    dialogues: List[ScriptDialogue] = []
    action: Optional[str] = None
    shot_hint: Optional[str] = None  # 镜头提示（≤20 字，景别+关键画面），拆分镜参考
    beat: Optional[str] = None
    summary: Optional[str] = None


class ScriptCreate(BaseModel):
    """手动新增场次"""
    project_id: str
    video_set_id: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None
    characters: Optional[List[str]] = None
    dialogues: Optional[List[ScriptDialogue]] = None
    action: Optional[str] = None
    shot_hint: Optional[str] = None
    beat: Optional[str] = None
    summary: Optional[str] = None


class ScriptUpdate(BaseModel):
    """剧本场次编辑"""
    location: Optional[str] = None
    time: Optional[str] = None
    characters: Optional[List[str]] = None
    dialogues: Optional[List[ScriptDialogue]] = None
    action: Optional[str] = None
    shot_hint: Optional[str] = None
    beat: Optional[str] = None
    summary: Optional[str] = None


# ============= 文生图模块 =============
class ImageGenerate(BaseModel):
    """文生图请求"""
    shot_id: str
    prompt: str
    neg_prompt: Optional[str] = None
    model_id: Optional[str] = None  # 文生图模型预设ID（model_type=image）
    model: Optional[str] = None  # 具体子模型（覆盖预设默认）
    prompt_id: Optional[str] = None  # 自定义出图提示词ID，空则用默认


class StoryboardGenerate(BaseModel):
    """四格分镜图请求：提示词由后端按段的 storyboard_prompt（四格文案）+ 人物外观 + 画风组装"""
    shot_id: str
    model_id: Optional[str] = None
    model: Optional[str] = None
    storyboard_prompt: Optional[str] = None  # 手改过的四格文案（空则用段上存的 / 现算的）


# ============= TTS模块 =============
class TTSGenerate(BaseModel):
    """TTS生成请求"""
    shot_id: str
    text: str
    voice_name: Optional[str] = None  # 不传则按说话角色绑定的音色，旁白用默认音色


class SRTExport(BaseModel):
    """SRT字幕导出"""
    project_id: str


# ============= 通用响应 =============
class ResponseModel(BaseModel):
    """通用响应"""
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None


class StyleSuggest(BaseModel):
    """风格 AI 识别：不传 text 时读本集（或作品）小说正文；apply=True 时直接写回作品"""
    video_set_id: Optional[str] = None
    text: Optional[str] = None
    model_id: Optional[str] = None
    model: Optional[str] = None
    apply: bool = False
