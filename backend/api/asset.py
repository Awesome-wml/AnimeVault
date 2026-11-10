"""资产参考图生成API：角色三视图、道具图、场景图；以及全量资产提取"""
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from bson import ObjectId
from pydantic import BaseModel, Field
from typing import Optional

from models.schema import ResponseModel, AssetExtract
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.image_provider import DoubaoImageProvider, image_size
from core.llm_factory import build_provider, build_image_provider
from core.prompt_registry import build_messages, build_prompt_text
from core.style_library import build_extract_style_block, build_style_art_prompt, style_ref
from core.script_text import load_script_text
from core.character_forms import character_face, character_forms, compose_description, form_index_of, set_form_image
from api.character import character_doc
from api.scene import scene_doc
from core.scene_views import scene_views, set_view_image, view_index_of
from core.sse import run_with_sse
from core.face_grid import apply_face_grid
from config.settings import settings
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/assets", tags=["资产参考图"])
logger = logging.getLogger(__name__)


class AssetGenerate(BaseModel):
    """生成资产参考图请求"""
    asset_type: str = Field(..., description="资产类型：character/prop/scene")
    asset_id: str = Field(..., description="资产ID（角色/道具/场景）")
    medium: Optional[str] = None  # 媒介 id，空则用资产所属项目的
    genre: Optional[str] = None  # 题材，空则用资产所属项目的
    style: Optional[str] = None  # 旧风格ID，兼容保留
    prompt_override: Optional[str] = None  # 可选：覆盖默认提示词
    model_id: Optional[str] = None  # 文生图模型预设ID（model_type=image）
    model: Optional[str] = None  # 具体子模型（覆盖预设默认）
    prompt_id: Optional[str] = None  # 自定义出图提示词ID，空则用默认
    form_index: Optional[int] = None  # 角色：生成第几个形态的三视图（从 0 起，默认第一形态）
    view_index: Optional[int] = None  # 场景：生成第几个视角的场景图（从 0 起，默认第一视角）


def get_image_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoImageProvider:
    """获取图像生成提供者：优先读 image 类型模型预设，空 Key 回退账号全局密钥。"""
    return build_image_provider(user, model_id, model)


GENDER_LABELS = {"male": "男性", "female": "女性"}
AGE_GROUP_LABELS = {
    "少年": "少年（约13到17岁）",
    "青年": "青年（约18到30岁）",
    "中年": "中年（约35到55岁）",
    "暮年": "暮年（约60岁以上）",
}
DEFAULT_ART_STYLE = "未指定，保持干净统一的设定图画风"


def build_asset_ref_prompt(asset_type: str, asset: dict, art_style: str,
                           form_index: int = 0, view_index: int = 0) -> str:
    """按资产类型组装参考图提示词（角色设定板 / 道具单品图 / 无人场景图）。

    模板来自 prompts/constraints.json（image 类整段出图描述），占位符运行时填入。
    form_index：角色的第几个形态（每个形态一张三视图：固定面部特征 + 该形态穿搭）。
    view_index：场景的第几个视角（每个视角一张无人场景图：同一描述 + 该视角机位 + 剧情状态）。
    """
    name = asset.get("name", "")
    description = asset.get("description", "") or "按名称合理设计"
    style = art_style or DEFAULT_ART_STYLE
    if asset_type == "character":
        gender = GENDER_LABELS.get((asset.get("gender") or "").lower(), "性别按人物设定")
        age_group = asset.get("age_group") or ""
        age_label = AGE_GROUP_LABELS.get(age_group, age_group or "按人物设定")
        form = character_forms(asset)[form_index_of(asset, form_index)]
        face = character_face(asset) or "按名称合理设计"
        outfit = form.get("outfit") or "按面部特征与年龄段合理搭配一套得体日常穿搭"
        return build_prompt_text(
            "character_sheet",
            character_name=name,
            character_face=face,
            form_name=form.get("name") or "",
            character_outfit=outfit,
            # 旧的自建模板仍用 {character_description}：面部 + 本形态穿搭
            character_description=compose_description(face, outfit) if asset.get("forms") else description,
            gender=gender,
            age_group=age_label,
            art_style=style,
        )
    if asset_type == "prop":
        return build_prompt_text(
            "prop_ref",
            prop_name=name,
            prop_type=asset.get("prop_type") or "道具",
            prop_description=description,
            art_style=style,
        )
    view = scene_views(asset)[view_index_of(asset, view_index)]
    state_note = (asset.get("state_note") or "").strip()
    camera = (view.get("camera") or "").strip()
    return build_prompt_text(
        "scene_ref",
        scene_name=name,
        scene_type=asset.get("scene_type") or "场景",
        scene_description=description,
        art_style=style,
        scene_state=state_note,
        view_name=view.get("name") or "",
        view_camera=camera,
        # 内置模板用下面两行：没有剧情状态 / 单视角无机位时整行消失
        scene_state_line=f"【物件状态】{state_note}\n" if state_note else "",
        scene_view_line=f"【机位视角】{view.get('name')}：{camera}，只改变机位，空间布局与物件状态不变\n" if camera else "",
    )


async def _get_asset(db, asset_type: str, asset_id: str, user_id: str):
    """获取资产文档并校验权限"""
    try:
        obj_id = ObjectId(asset_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的资产ID")

    collection_map = {
        "character": db.characters,
        "prop": db.props,
        "scene": db.scenes,
    }
    collection = collection_map.get(asset_type)
    if collection is None:
        raise HTTPException(status_code=400, detail=f"不支持的资产类型: {asset_type}")

    asset = await collection.find_one({"_id": obj_id, "user_id": user_id})
    if asset is None:
        raise HTTPException(status_code=404, detail="资产不存在")
    return asset


@router.post("/generate")
async def generate_asset_image(data: AssetGenerate, user: dict = Depends(get_current_user)):
    """生成资产参考图（角色三视图/道具图/场景图）"""
    db = get_db()
    user_id = str(user["_id"])

    # 获取资产
    asset = await _get_asset(db, data.asset_type, data.asset_id, user_id)
    name = asset.get("name", "")
    # 风格只来自项目：请求里没传的字段回退到资产所属项目的媒介 / 题材 / 旧风格
    project = None
    if asset.get("project_id") and ObjectId.is_valid(asset["project_id"]):
        project = await db.projects.find_one({"_id": ObjectId(asset["project_id"]), "user_id": user_id})
    # 预置媒介取中文画风词 + 题材色调；自定义风格（不在库里）直接用其文字
    art_style = build_style_art_prompt(**style_ref(project, medium=data.medium, genre=data.genre, style_id=data.style))

    image_provider = get_image_provider(user, data.model_id, data.model)

    try:
        # 构建提示词
        if data.prompt_override:
            prompt = data.prompt_override
        else:
            prompt = build_asset_ref_prompt(data.asset_type, asset, art_style,
                                            form_index=data.form_index or 0, view_index=data.view_index or 0)

        # 角色设定板横版分栏，道具/场景方形；尺寸按所选模型档位取合规值
        orientation = "landscape" if data.asset_type == "character" else "square"
        gen_w, gen_h = image_size(image_provider.model, orientation)
        image_data = await image_provider.generate_image(
            prompt=prompt, width=gen_w, height=gen_h
        )

        # 角色设定板：可选叠加皮肤/脸部线框网格，弱化真人肖像识别度
        if data.asset_type == "character" and settings.FACE_GRID_ENABLED:
            image_data = apply_face_grid(
                image_data,
                cell=settings.FACE_GRID_CELL,
                alpha=settings.FACE_GRID_ALPHA,
                diagonal=settings.FACE_GRID_DIAGONAL,
            )

        # 保存图片
        img_path = FileUtil.save_image(image_data, ext="png")

        # 更新资产记录（角色：写到对应形态，第一形态同步旧字段 image_path）
        form_index = await _save_asset_image(db, data.asset_type, asset, img_path,
                                             data.view_index if data.asset_type == "scene" else data.form_index)

        return ResponseModel(
            message=f"{name} 参考图生成成功",
            data={"img_path": img_path, "model": image_provider.model, "size": [gen_w, gen_h],
                  "form_index": form_index if data.asset_type != "scene" else None,
                  "view_index": form_index if data.asset_type == "scene" else None}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"参考图生成失败: {str(e)}")


async def _save_asset_image(db, asset_type: str, asset: dict, img_path: str, form_index=None) -> Optional[int]:
    """参考图写回资产记录。角色按形态写（core.character_forms.set_form_image），返回实际写入的形态下标。"""
    collection_map = {
        "character": db.characters,
        "prop": db.props,
        "scene": db.scenes,
    }
    if asset_type == "character":
        idx = form_index_of(asset, form_index)
        update = set_form_image(asset, idx, img_path)
    elif asset_type == "scene":
        idx = view_index_of(asset, form_index)
        update = set_view_image(asset, idx, img_path)
    else:
        idx, update = None, {"image_path": img_path}
    await collection_map[asset_type].update_one({"_id": asset["_id"]}, {"$set": update})
    return idx


@router.post("/upload")
async def upload_asset_image(
    asset_type: str,
    asset_id: str,
    file: UploadFile = File(...),
    form_index: Optional[int] = None,
    view_index: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """人工上传资产参考图（角色三视图/道具图/场景图），保存并写回 image_path"""
    db = get_db()
    user_id = str(user["_id"])

    # 校验资产
    asset = await _get_asset(db, asset_type, asset_id, user_id)
    name = asset.get("name", "")

    # 校验文件类型
    content_type = file.content_type or ""
    if not (content_type.startswith("image/")):
        raise HTTPException(status_code=400, detail="只支持上传图片文件")

    # 读取文件内容
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取上传文件失败: {str(e)}")
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")

    # 确定扩展名
    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = ext_map.get(content_type, "png")

    # 保存图片
    img_path = FileUtil.save_image(data, ext=ext)

    # 写回资产记录（角色：写到对应形态）
    idx = await _save_asset_image(db, asset_type, asset, img_path,
                                  view_index if asset_type == "scene" else form_index)

    return ResponseModel(
        message=f"{name} 参考图上传成功",
        data={"img_path": img_path, "form_index": idx if asset_type != "scene" else None,
              "view_index": idx if asset_type == "scene" else None}
    )


@router.post("/extract-all")
async def extract_all_assets(data: AssetExtract, user: dict = Depends(get_current_user)):
    """全量提取：一次调用同时提取角色/道具/场景，分块落库；SSE 流式推进度。"""
    db = get_db()
    user_id = str(user["_id"])

    # 校验项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": user_id
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    logger.info(f"[资产] 收到全量提取请求: project_id={data.project_id}, 小说 {len(data.novel_text or '')} 字")
    llm = build_provider(user, data.model_id, data.model)
    logger.info(f"[资产] 使用模型: model_id={data.model_id or '全局默认'}, model={data.model or '默认'}")
    # 风格段落；真人类风格追加面部真实质感要求（core.style_library.build_extract_style_block）
    style_block = build_extract_style_block(medium=data.medium, genre=data.genre, style_id=data.style)

    # 优先基于本集剧本场次抽取；无剧本时兜底小说原文（资产仍落项目级共享）
    script_text, scene_count = await load_script_text(db, data.project_id, data.video_set_id)
    source_text = script_text or data.novel_text or ""
    if len(source_text) > settings.ASSET_EXTRACT_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"{'剧本' if script_text else '小说'}超过 "
                            f"{settings.ASSET_EXTRACT_MAX_CHARS} 字，请分集提取")
    logger.info(f"[资产] 抽取依据: {'剧本 ' + str(scene_count) + ' 场' if script_text else '小说原文'}")

    messages = build_messages(
        "asset_extract",
        variant=project.get("genre"),
        novel_text=source_text,
        style_block=style_block,
    )
    logger.info(f"[资产] 提示词已组装: 最终请求 {len(messages[-1]['content'])} 字, prompt_id={data.prompt_id or '默认'}")

    async def build_task(report):
        logger.info("[资产] 开始调用大模型提取资产...")
        result = await llm.chat_json(messages, on_progress=report)

        characters = result.get("characters", []) or []
        props = result.get("props", []) or []
        scenes = result.get("scenes", []) or []
        logger.info(f"[资产] 模型返回: 角色 {len(characters)}, 道具 {len(props)}, 场景 {len(scenes)}")

        # 角色解析与单项提取共用 api.character.character_doc（face / forms / voice）
        char_docs = [character_doc(user_id, data.project_id, c) for c in characters
                     if isinstance(c, dict) and c.get("name")]
        if char_docs:
            await db.characters.insert_many(char_docs)

        prop_docs = [
            {
                "user_id": user_id,
                "project_id": data.project_id,
                "name": p.get("name", ""),
                "prop_type": p.get("prop_type", ""),
                "description": p.get("description", ""),
                "image_path": None,
            }
            for p in props if p.get("name")
        ]
        if prop_docs:
            await db.props.insert_many(prop_docs)

        scene_docs = [scene_doc(user_id, data.project_id, s) for s in scenes
                      if isinstance(s, dict) and s.get("name")]
        if scene_docs:
            await db.scenes.insert_many(scene_docs)

        return (
            f"提取完成：角色{len(char_docs)}、道具{len(prop_docs)}、场景{len(scene_docs)}",
            {
                "characters": len(char_docs),
                "props": len(prop_docs),
                "scenes": len(scene_docs),
            },
        )

    return await run_with_sse(build_task)
