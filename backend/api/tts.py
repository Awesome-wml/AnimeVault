"""TTS语音合成API"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from bson import ObjectId

from models.schema import TTSGenerate, SRTExport, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.providers.tts_provider import DoubaoTTSProvider
from core.providers.llm_provider import DoubaoLLMProvider
from core.voice_matcher import match_voices
from utils.file_util import FileUtil
from utils.srt_builder import SRTBuilder

router = APIRouter(prefix="/api/tts", tags=["语音合成"])


def get_tts_provider(user: dict) -> DoubaoTTSProvider:
    """获取TTS提供者"""
    api_key = user.get("doubao_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置豆包API密钥")
    
    base_url = user.get("doubao_base_url", "https://ark.cn-beijing.volces.com/api/v3")
    return DoubaoTTSProvider(api_key=api_key, base_url=base_url)


@router.get("/voices")
async def get_voices(user: dict = Depends(get_current_user)):
    """获取可用音色列表"""
    tts_provider = DoubaoTTSProvider(api_key="dummy")
    voices = tts_provider.get_available_voices()
    return ResponseModel(data={"voices": voices})


@router.post("/generate")
async def generate_tts(data: TTSGenerate, user: dict = Depends(get_current_user)):
    """生成语音"""
    db = get_db()
    
    # 检查分镜权限
    try:
        shot = await db.shots.find_one({
            "_id": ObjectId(data.shot_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    # 确定音色：优先根据分镜的说话角色自动匹配角色绑定的音色，保证同一角色全视频音色一致
    voice_name = data.voice_name
    char_name = shot.get("character_name")
    if not voice_name and char_name and char_name != "旁白":
        # 查该角色绑定的音色
        char = await db.characters.find_one({
            "user_id": str(user["_id"]),
            "project_id": shot.get("project_id"),
            "name": char_name
        })
        if char and char.get("voice_name"):
            voice_name = char["voice_name"]
    if not voice_name:
        # 默认音色（旁白或未指定）
        voice_name = "zh_female_qingxin"

    # 获取TTS提供者
    tts_provider = get_tts_provider(user)

    try:
        # 生成语音
        audio_data = await tts_provider.generate_speech(
            text=data.text,
            voice_name=voice_name
        )
        
        # 保存音频
        audio_path = FileUtil.save_audio(audio_data, ext="mp3")
        
        # 更新分镜记录
        await db.shots.update_one(
            {"_id": ObjectId(data.shot_id)},
            {"$set": {"audio_path": audio_path}}
        )
        
        return ResponseModel(
            message="语音生成成功",
            data={"audio_path": audio_path}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音生成失败: {str(e)}")


@router.post("/srt/export")
async def export_srt(data: SRTExport, user: dict = Depends(get_current_user)):
    """导出SRT字幕"""
    db = get_db()
    
    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(data.project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 获取所有分镜
    cursor = db.shots.find({
        "user_id": str(user["_id"]),
        "project_id": data.project_id
    }).sort("shot_no", 1)
    
    shots = await cursor.to_list(length=500)
    
    if not shots:
        raise HTTPException(status_code=404, detail="该项目没有分镜数据")
    
    # 构建SRT
    try:
        srt_content = SRTBuilder.build_srt(shots)
        
        # 保存SRT文件
        srt_filename = f"{data.project_id}.srt"
        srt_path = FileUtil.get_static_dir() / srt_filename
        
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        
        return ResponseModel(
            message="SRT字幕生成成功",
            data={
                "srt_path": srt_filename,
                "shot_count": len(shots)
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRT生成失败: {str(e)}")


@router.post("/auto-assign")
async def auto_assign_voice(project_id: str, user: dict = Depends(get_current_user)):
    """根据角色切片特征(gender/age_group/trait)确定性匹配音色，main/support配音，extra路人跳过"""
    db = get_db()

    # 检查项目权限
    try:
        project = await db.projects.find_one({
            "_id": ObjectId(project_id),
            "user_id": str(user["_id"])
        })
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 全量获取项目角色
    cursor = db.characters.find({
        "user_id": str(user["_id"]),
        "project_id": project_id
    })
    all_roles = await cursor.to_list(length=100000)
    if not all_roles:
        raise HTTPException(status_code=400, detail="该项目没有角色，请先提取角色")

    # 用确定性匹配引擎分配音色
    assigned = match_voices(all_roles)
    extras = [c for c in all_roles if (c.get("importance") or "support") not in ("main", "support")]

    # 写回数据库
    updated = 0
    for a in assigned:
        if a.get("voice"):
            await db.characters.update_one(
                {"user_id": str(user["_id"]), "project_id": project_id, "name": a["name"]},
                {"$set": {"voice_name": a["voice"]}}
            )
            updated += 1

    # 统计音色是否重复
    voices_used = [a["voice"] for a in assigned if a.get("voice")]
    return ResponseModel(
        message=f"已为{updated}个主要角色匹配音色（{len(extras)}个路人跳过）",
        data={
            "assigned": assigned,
            "skipped_extras": len(extras),
            "duplicate_count": len(voices_used) - len(set(voices_used))
        }
    )


@router.get("/srt/download/{project_id}")
async def download_srt(project_id: str, user: dict = Depends(get_current_user)):
    """下载SRT字幕文件"""
    srt_filename = f"{project_id}.srt"
    srt_path = FileUtil.get_static_dir() / srt_filename
    
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="SRT文件不存在，请先导出")
    
    return FileResponse(
        path=srt_path,
        filename=f"subtitles_{project_id}.srt",
        media_type="application/x-subrip"
    )
