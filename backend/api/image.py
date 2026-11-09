"""文生图API：单张首帧（旧格式分镜）与四格分镜图（视频段，作视频参考图）"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from models.schema import ImageGenerate, StoryboardGenerate, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.llm_factory import build_image_provider
from core.providers.image_provider import DoubaoImageProvider, image_size
from core.storyboard import storyboard_body, storyboard_prompt
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
    if not (shot.get("beats") or shot.get("lines")):
        raise HTTPException(status_code=400, detail="旧格式镜头没有小镜头，请用“生成画面”出单张首帧")

    project = await _project_of(db, shot)
    art_style = build_style_art_prompt(**style_ref(project))
    genre = str((project or {}).get("genre") or "")
    chars = await db.characters.find({"project_id": shot["project_id"]}).to_list(None)
    scenes = await db.scenes.find({"project_id": shot["project_id"]}).to_list(None)
    props = await db.props.find({"project_id": shot["project_id"]}).to_list(None)

    body = (data.storyboard_prompt or "").strip() or (shot.get("storyboard_prompt") or "").strip() \
        or storyboard_body(shot, genre)
    prompt = storyboard_prompt(body, shot, chars, art_style, genre)

    # 参考图接口：角色（按场次选形态）→ 场景 → 道具，只传本地存在的
    from core.asset_binding import collect_bindings
    static_dir = FileUtil.get_static_dir()
    refs = []
    for b in collect_bindings(shot, chars, scenes, props):
        f = static_dir / b["img"] if b.get("img") else None
        if f and f.exists():
            refs.append(str(f))

    image_provider = get_image_provider(user, data.model_id, data.model)
    try:
        gen_w, gen_h = image_size(image_provider.model, "square")
        image_data = await image_provider.generate_image(prompt=prompt, width=gen_w, height=gen_h,
                                                         reference_images=refs)
        path = FileUtil.save_image(image_data, ext="png")
        update = {"storyboard_path": path}
        if body != (shot.get("storyboard_prompt") or ""):
            update["storyboard_prompt"] = body
        await db.shots.update_one({"_id": shot["_id"]}, {"$set": update})
        logger.info(f"[四格分镜] 段 {shot.get('shot_no')} 已生成 {gen_w}x{gen_h}，参考图 {len(refs)} 张")
        return ResponseModel(message="四格分镜已生成",
                             data={"storyboard_path": path, "storyboard_prompt": body, "prompt": prompt,
                                   "size": [gen_w, gen_h], "reference_count": len(refs)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"四格分镜生成失败: {str(e)}")
