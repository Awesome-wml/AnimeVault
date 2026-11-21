"""文生图API：单张首帧（旧格式分镜）与四格分镜图（视频段，作视频参考图）"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from models.schema import ImageGenerate, StoryboardGenerate, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.llm_factory import build_image_provider
from core.providers.image_provider import DoubaoImageProvider, image_size
from core.providers import fake
from core.providers.image_provider import supports_reference_images
from core.storyboard import asset_sheet, fresh_storyboard_body, panel_prompt, storyboard_body, storyboard_panels, storyboard_prompt
from core.storyboard_image import compose_grid, looks_like_grid
from core.style_library import build_style_art_prompt, style_ref
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/image", tags=["文生图"])
logger = logging.getLogger(__name__)


def get_image_provider(user: dict, model_id: str = None, model: str = None) -> DoubaoImageProvider:
    """获取图像生成提供者：优先读 image 类型模型预设，空 Key 回退账号全局密钥。"""
    return build_image_provider(user, model_id, model)


async def _own_shot(db, shot_id: str, user: dict) -> dict:
    try:
        shot = await db.shots.find_one({"_id": ObjectId(shot_id), "user_id": str(user["_id"])})
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return shot


async def _project_of(db, shot: dict):
    # 分镜里 project_id 存的是字符串，必须转回 ObjectId 才能查到项目
    if shot.get("project_id") and ObjectId.is_valid(shot["project_id"]):
        return await db.projects.find_one({"_id": ObjectId(shot["project_id"])})
    return None


@router.post("/generate")
async def generate_image(data: ImageGenerate, user: dict = Depends(get_current_user)):
    """生成单张首帧画面（旧格式分镜；视频段请用 /storyboard 生成四格分镜图）"""
    db = get_db()
    shot = await _own_shot(db, data.shot_id, user)

    # 获取图像生成提供者（按所选模型预设/子模型）
    image_provider = get_image_provider(user, data.model_id, data.model)

    # 读取分镜所属项目的风格，注入绘画指令保证画面统一
    project = await _project_of(db, shot)
    art_style = build_style_art_prompt(**style_ref(project))
    final_prompt = data.prompt
    if art_style and art_style not in final_prompt:
        final_prompt = final_prompt + ", " + art_style

    try:
        # 按所选模型档位取合规横屏尺寸
        gen_w, gen_h = image_size(image_provider.model, "landscape")
        image_data = await image_provider.generate_image(
            prompt=final_prompt,
            neg_prompt=data.neg_prompt,
            width=gen_w,
            height=gen_h
        )
        img_path = FileUtil.save_image(image_data, ext="png")
        await db.shots.update_one({"_id": shot["_id"]}, {"$set": {"img_path": img_path}})
        return ResponseModel(message="图片生成成功", data={"img_path": img_path})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片生成失败: {str(e)}")


@router.post("/storyboard")
async def generate_storyboard(data: StoryboardGenerate, user: dict = Depends(get_current_user)):
    """生成本段的 2×2 四格分镜图（方图）：四格文案 + 人物外观（面部 + 本场次穿搭）+ 项目画风。

    参考图（角色形态图、场景图、道具图）按绑定顺序传给 provider 的 reference_images；当前 glm-image /
    cogview 不支持参考图，provider 只记日志，人物一致性靠文字外观描述。
    """
    db = get_db()
    shot = await _own_shot(db, data.shot_id, user)
    if not (shot.get("beats") or shot.get("lines") or shot.get("video_prompt") or shot.get("prompt")):
        raise HTTPException(status_code=400, detail="旧格式镜头没有小镜头，请用“生成画面”出单张首帧")

    project = await _project_of(db, shot)
    art_style = build_style_art_prompt(**style_ref(project))
    genre = str((project or {}).get("genre") or "")
    chars = await db.characters.find({"project_id": shot["project_id"]}).to_list(None)
    scenes = await db.scenes.find({"project_id": shot["project_id"]}).to_list(None)
    props = await db.props.find({"project_id": shot["project_id"]}).to_list(None)

    # 段上存的四格文案是旧写法且没手改过时，换成新写法（不用重新拆分镜，重新出图即可）
    body = (data.storyboard_prompt or "").strip() or fresh_storyboard_body(shot, genre) \
        or storyboard_body(shot, genre) \
        or str(shot.get("video_prompt") or shot.get("prompt") or "").strip()
    # 画面跟资产挂钩：人物、场景、道具都照资产页画，不让出图模型自由设计
    static_dir = FileUtil.get_static_dir()
    script = await db.scripts.find_one({"project_id": shot["project_id"], "scene_no": shot.get("scene_no")}) \
        if shot.get("scene_no") is not None else None
    sheet = asset_sheet(shot, chars, scenes, props, static_dir, scene_location=(script or {}).get("location") or "")
    if sheet["missing"]:
        raise HTTPException(status_code=400, detail="这一段的画面还不能生成：" + "；".join(sheet["missing"]))
    image_provider = get_image_provider(user, data.model_id, data.model)
    with_refs = supports_reference_images(image_provider.model)
    if with_refs:
        # 出图模型收参考图：角色必须先有参考图，否则“照着资产画”无从谈起
        no_img = [w for w in sheet["warnings"] if w.startswith("角色") and "还没有参考图" in w]
        if no_img:
            raise HTTPException(status_code=400, detail="这一段的画面还不能生成：" + "；".join(no_img) + "。先在角色页生成参考图")
    refs = [r["path"] for r in sheet["refs"]]
    prompt = storyboard_prompt(body, shot, chars, art_style, genre, sheet=sheet, with_refs=with_refs)

    try:
        gen_w, gen_h = image_size(image_provider.model, "square")
        image_data = await image_provider.generate_image(prompt=prompt, width=gen_w, height=gen_h,
                                                         reference_images=refs)
        mode = "grid"
        panels = storyboard_panels(shot) if shot.get("beats") else []
        if len(panels) == 4 and not fake.enabled() and not looks_like_grid(image_data):
            # 没画成四格（出过单张人像、黑白速写这类跑题图）：重试一次，还不行就逐格出图再拼
            logger.warning(f"[四格分镜] 段 {shot.get('shot_no')} 出图不是四格，重试")
            image_data = await image_provider.generate_image(prompt=prompt, width=gen_w, height=gen_h,
                                                             reference_images=refs)
            mode = "grid_retry"
            if not looks_like_grid(image_data):
                logger.warning(f"[四格分镜] 段 {shot.get('shot_no')} 重试仍不是四格，改为逐格出图再拼")
                singles = []
                for pnl in panels:
                    singles.append(await image_provider.generate_image(
                        prompt=panel_prompt(shot, pnl, chars, art_style, genre, sheet=sheet, with_refs=with_refs), width=gen_w, height=gen_h,
                        reference_images=refs))
                image_data = compose_grid(singles, gen_w)
                mode = "panels"
        path = FileUtil.save_image(image_data, ext="png")
        update = {"storyboard_path": path}
        if body != (shot.get("storyboard_prompt") or ""):
            update["storyboard_prompt"] = body
        await db.shots.update_one({"_id": shot["_id"]}, {"$set": update})
        logger.info(f"[四格分镜] 段 {shot.get('shot_no')} 已生成 {gen_w}x{gen_h}，参考图 {len(refs)} 张")
        return ResponseModel(message="四格分镜已生成",
                             data={"storyboard_path": path, "storyboard_prompt": body, "prompt": prompt,
                                   "size": [gen_w, gen_h], "reference_count": len(refs) if with_refs else 0, "mode": mode,
                                   "assets": [{"type": b["asset_type"], "name": b["name"], "has_image": bool(b.get("img"))}
                                              for b in sheet["bindings"]],
                                   "references_used": with_refs, "asset_warnings": sheet["warnings"]
                                   + ([] if with_refs else ["当前出图模型不收参考图，画面只按资产的文字设定画；"
                                                            "要照着资产图画，请换用支持参考图的出图模型（如 Seedream）"])})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"四格分镜生成失败: {str(e)}")
