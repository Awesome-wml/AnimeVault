from pydantic import BaseModel, Field
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
    doubao_model: Optional[str] = "glm-4.7-flash"


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
    genre: Optional[str] = None
    style: Optional[str] = None


class ProjectUpdate(BaseModel):
    """更新项目"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    novel_content: Optional[str] = None
    genre: Optional[str] = None
    style: Optional[str] = None


class ProjectInfo(BaseModel):
    """项目信息"""
    id: str
    user_id: str
    name: str
    novel_content: Optional[str] = None
    genre: Optional[str] = None
    style: Optional[str] = None
    create_time: datetime


# ============= 小说生成 =============
class NovelGenerate(BaseModel):
    """小说生成请求"""
    project_id: str
    genre: str = Field(..., description="题材，如：都市、玄幻、古风")
    style: str = Field(..., description="风格，如：轻松搞笑、悬疑烧脑")
    outline: str = Field(..., description="故事梗概")
    protagonist: str = Field(..., description="主角设定")
    target_words: int = Field(default=5000, ge=1000, le=50000, description="目标字数")


# ============= 角色模块 =============
class CharacterCreate(BaseModel):
    """创建角色"""
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    voice_name: Optional[str] = None
    importance: Optional[str] = None  # main核心 / support配角 / extra路人
    gender: Optional[str] = None      # male/female
    age_group: Optional[str] = None   # 少年/青年/中年/暮年
    trait: Optional[str] = None       # 特质：阳刚/阴森/温柔/阳光/威严...


class CharacterUpdate(BaseModel):
    """更新角色"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    voice_name: Optional[str] = None
    image_path: Optional[str] = None
    importance: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    trait: Optional[str] = None


class CharacterInfo(BaseModel):
    """角色信息"""
    id: str
    user_id: str
    project_id: str
    name: str
    description: Optional[str] = None
    voice_name: Optional[str] = None
    image_path: Optional[str] = None
    importance: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    trait: Optional[str] = None


class CharacterExtract(BaseModel):
    """AI提取角色"""
    project_id: str
    novel_text: str
    style: Optional[str] = None  # 风格ID，可选


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
    style: Optional[str] = None  # 风格ID，可选


# ============= 场景模块 =============
class SceneCreate(BaseModel):
    """创建场景"""
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    scene_type: Optional[str] = None  # 场景类型，如：室内、室外、宫殿
    description: Optional[str] = None
    image_path: Optional[str] = None


class SceneUpdate(BaseModel):
    """更新场景"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    scene_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None


class SceneInfo(BaseModel):
    """场景信息"""
    id: str
    user_id: str
    project_id: str
    name: str
    scene_type: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None


class SceneExtract(BaseModel):
    """AI提取场景"""
    project_id: str
    novel_text: str
    style: Optional[str] = None  # 风格ID，可选


# ============= 分镜模块 =============
class ShotCreate(BaseModel):
    """创建分镜"""
    project_id: str
    shot_no: int
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
    duration: Optional[float] = Field(None, ge=0.5, le=30.0)
    img_path: Optional[str] = None
    audio_path: Optional[str] = None
    character_name: Optional[str] = None


class ShotInfo(BaseModel):
    """分镜信息"""
    id: str
    user_id: str
    project_id: str
    shot_no: int
    text: str
    prompt: Optional[str] = None
    neg_prompt: Optional[str] = None
    duration: float
    img_path: Optional[str] = None
    audio_path: Optional[str] = None
    character_name: Optional[str] = None


class ShotSplit(BaseModel):
    """AI拆分分镜"""
    project_id: str
    novel_paragraph: str


# ============= 文生图模块 =============
class ImageGenerate(BaseModel):
    """文生图请求"""
    shot_id: str
    prompt: str
    neg_prompt: Optional[str] = None


# ============= TTS模块 =============
class TTSGenerate(BaseModel):
    """TTS生成请求"""
    shot_id: str
    text: str
    voice_name: Optional[str] = "zh_female_qingxin"


class SRTExport(BaseModel):
    """SRT字幕导出"""
    project_id: str


# ============= 通用响应 =============
class ResponseModel(BaseModel):
    """通用响应"""
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None
