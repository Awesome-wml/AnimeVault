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
from core.prompt_tpl import CHARACTER_SHEET_PROMPT, ASSET_EXTRACT_PROMPT
from core.llm_factory import build_provider, build_image_provider, resolve_prompt, safe_format
from core.style_library import build_style_block, build_style_art_prompt
from core.script_text import scripts_to_text
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
    style: Optional[str] = None  # 风格ID
    prompt_override: Optional[str] = None  # 可选：覆盖默认提示词
    model_id: Optional[str] = None  # 文生图模型预设ID（model_type=image）
    model: Optional[str] = None  # 具体子模型（覆盖预设默认）
    prompt_id: Optional[str] = None  # 自定义出图提示词ID，空则用默认


def get_image_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoImageProvider:
    """获取图像生成提供者：优先读 image 类型模型预设，空 Key 回退账号全局密钥。"""
    return build_image_provider(user, model_id, model)


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
    description = asset.get("description", "")
    art_style = build_style_art_prompt(data.style)

    image_provider = get_image_provider(user, data.model_id, data.model)

    try:
        # 构建提示词
        if data.prompt_override:
            prompt = data.prompt_override
        elif data.asset_type == "character":
            # 角色三视图设定板：可选 prompt_id 覆盖默认模板，再注入角色名/描述/风格
            sheet_tpl = resolve_prompt(data.prompt_id, "character_sheet", CHARACTER_SHEET_PROMPT)
            prompt = safe_format(
                sheet_tpl,
                character_name=name,
                character_description=description,
                art_style=art_style,
            )
        else:
            # 道具/场景参考图
            type_label = "道具" if data.asset_type == "prop" else "场景"
            style_suffix = f"，风格指令：{art_style}" if art_style else ""
            prompt = (
                f"一张{type_label}参考图。"
                f"{type_label}名称：{name}。"
                f"{type_label}描述：{description}。"
                f"构图居中、主体清晰、浅色纯背景，适合作为参考图。"
                f"{style_suffix}"
            )

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

        # 更新资产记录
        collection_map = {
            "character": db.characters,
            "prop": db.props,
            "scene": db.scenes,
        }
        await collection_map[data.asset_type].update_one(
            {"_id": ObjectId(data.asset_id)},
            {"$set": {"image_path": img_path}}
        )

        return ResponseModel(
            message=f"{name} 参考图生成成功",
            data={"img_path": img_path}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"参考图生成失败: {str(e)}")

@router.post("/upload")
async def upload_asset_image(
    asset_type: str,
    asset_id: str,
    file: UploadFile = File(...),
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

    # 写回资产记录
    collection_map = {
        "character": db.characters,
        "prop": db.props,
        "scene": db.scenes,
    }
    await collection_map[asset_type].update_one(
        {"_id": ObjectId(asset_id)},
        {"$set": {"image_path": img_path}}
    )

    return ResponseModel(
        message=f"{name} 参考图上传成功",
        data={"img_path": img_path}
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
    style_block = build_style_block(data.style) if data.style else ""

    # 优先基于剧本场次抽取；无剧本时兜底小说原文
    scripts = await db.scripts.find({"project_id": data.project_id}).to_list(None)
    source_text = scripts_to_text(scripts) if scripts else data.novel_text
    logger.info(f"[资产] 抽取依据: {'剧本 ' + str(len(scripts)) + ' 场' if scripts else '小说原文'}")

    tpl = resolve_prompt(
        data.prompt_id, "asset_extract", ASSET_EXTRACT_PROMPT,
        category=project.get("genre"),
    )
    prompt = safe_format(
        tpl,
        novel_text=source_text[:5000],
        style_block=style_block,
    )
    logger.info(f"[资产] 提示词已组装: 模板 {len(tpl)} 字, 最终请求 {len(prompt)} 字, prompt_id={data.prompt_id or '默认'}")
    messages = [{"role": "user", "content": prompt}]

    async def build_task(report):
        logger.info("[资产] 开始调用大模型提取资产...")
        result = await llm.chat_json(messages, on_progress=report)

        characters = result.get("characters", []) or []
        props = result.get("props", []) or []
        scenes = result.get("scenes", []) or []
        logger.info(f"[资产] 模型返回: 角色 {len(characters)}, 道具 {len(props)}, 场景 {len(scenes)}")

        char_docs = [
            {
                "user_id": user_id,
                "project_id": data.project_id,
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "importance": c.get("importance", "support"),
                "gender": c.get("gender"),
                "age_group": c.get("age_group"),
                "trait": c.get("trait"),
                "voice_name": None,
                "image_path": None,
            }
            for c in characters if c.get("name")
        ]
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

        scene_docs = [
            {
                "user_id": user_id,
                "project_id": data.project_id,
                "name": s.get("name", ""),
                "scene_type": s.get("scene_type", ""),
                "description": s.get("description", ""),
                "image_path": None,
            }
            for s in scenes if s.get("name")
        ]
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
