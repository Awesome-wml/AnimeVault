"""分镜管理API"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import ShotCreate, ShotUpdate, ShotInfo, ShotSplit, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import SHOT_SPLIT_PROMPT
from core.llm_factory import build_provider, resolve_prompt, safe_format
from core.shot_timing import (NARRATOR, fill_rate, is_segment, legacy_fields, normalize_duration,
                              normalize_segment, rebalance_segments, retime_segment, speech_seconds,
                              unsourced_lines)
from core.shot_split import (MAX_SPLIT_CHARS, ShotSplitTruncated, clear_progress, get_progress, link_continuity,
                             set_progress, split_in_chunks)
from core.shot_voice import split_mixed_voice
from config.settings import settings
from core.video_models import get_video_model, segment_budget, segment_params
from core.video_prompt import assemble_video_prompt, collect_refs, filter_refs, speaker_warnings
from core.style_library import build_style_block, build_style_art_prompt, build_genre_rhythm
from utils.file_util import FileUtil

router = APIRouter(prefix="/api/shots", tags=["分镜管理"])
logger = logging.getLogger(__name__)

GENDER_SHORT = {"male": "男", "female": "女"}


def build_asset_block(chars: list, scenes: list, props: list) -> str:
    """把项目已有资产组成「已有资产清单」，供分镜绑定时原样引用名字。"""
    if not (chars or scenes or props):
        return "（暂无已有资产，角色、场景、道具按原文命名）"
    # 同名资产（如重复提取）只列一次
    chars = list({c["name"]: c for c in chars}.values())
    scenes = list({s["name"]: s for s in scenes}.values())
    props = list({p["name"]: p for p in props}.values())
    lines = []
    if chars:
        items = []
        for c in chars:
            tags = "、".join(t for t in (GENDER_SHORT.get(c.get("gender") or ""), c.get("age_group") or "") if t)
            items.append(f"{c['name']}（{tags}）" if tags else c["name"])
        lines.append("角色：" + "，".join(items))
    if scenes:
        lines.append("场景：" + "，".join(s["name"] for s in scenes))
    if props:
        lines.append("道具：" + "，".join(p["name"] for p in props))
    return "\n".join(lines)


def _name_list(value, allowed: set) -> list:
    """规整模型返回的名字数组；有资产清单时只保留清单里的名字。"""
    if isinstance(value, str):
        value = [v.strip() for v in value.replace("、", ",").replace("，", ",").split(",")]
    if not isinstance(value, list):
        return []
    names = []
    for v in value:
        v = str(v).strip() if v is not None else ""
        if v and v not in names and (not allowed or v in allowed):
            names.append(v)
    return names



@router.post("/split")
async def split_shots(data: ShotSplit, user: dict = Depends(get_current_user)):
    """AI拆分分镜"""
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

    logger.info(f"[分镜] 收到拆分镜请求: project_id={data.project_id}, 小说段落 {len(data.novel_paragraph or '')} 字")

    # 解析要绑定的视频分组：优先请求传入，否则取项目默认分组
    target_set_id = (data.video_set_id or "").strip()
    if not target_set_id:
        vset = await db.video_sets.find_one({"project_id": data.project_id})
        if vset:
            target_set_id = str(vset["_id"])
    logger.info(f"[分镜] 绑定视频分组: {target_set_id or '未分组'}")

    # 获取LLM提供者（可按模型预设覆盖）
    llm = build_provider(user, data.model_id, data.model)
    logger.info(f"[分镜] 使用模型: model_id={data.model_id or '全局默认'}, model={data.model or '默认'}")

    # 读取项目风格，注入到分镜拆分提示词（可按提示词ID覆盖）
    style_id = project.get("style")
    style_block = build_style_block(style_id) if style_id else ""

    # 已有资产清单：要求模型绑定角色/场景/道具时只用这些名字
    proj_filter = {"project_id": data.project_id, "user_id": str(user["_id"])}
    asset_fields = {"name": 1, "gender": 1, "age_group": 1}
    chars = [c for c in await db.characters.find(proj_filter, asset_fields).to_list(None) if c.get("name")]
    scenes = [c for c in await db.scenes.find(proj_filter, {"name": 1}).to_list(None) if c.get("name")]
    props = [c for c in await db.props.find(proj_filter, {"name": 1}).to_list(None) if c.get("name")]
    asset_block = build_asset_block(chars, scenes, props)
    char_names = {c["name"] for c in chars}
    prop_names = {p["name"] for p in props}
    logger.info(f"[分镜] 已有资产: 角色 {len(chars)}, 场景 {len(scenes)}, 道具 {len(props)}")

    # 视频模型：段时长目标取模型的 max_duration，参数注入模板
    model = get_video_model(project.get("video_model"))
    novel = (data.novel_paragraph or "").strip()
    if len(novel) > MAX_SPLIT_CHARS:
        raise HTTPException(status_code=400, detail=f"小说超过 {MAX_SPLIT_CHARS} 字，请分集拆分镜")

    tpl = resolve_prompt(data.prompt_id, "split_shots", SHOT_SPLIT_PROMPT, category=project.get("genre"))
    style_rhythm = build_genre_rhythm(project.get("genre"), style_id)
    seg_static = segment_params(model)

    def render(chunk_text: str, note: str) -> str:
        """每块都注入资产清单、风格与题材节奏；段数预算按本块朗读量算。"""
        return safe_format(
            tpl,
            novel_paragraph=chunk_text,
            chunk_note=note,
            style_block=style_block,
            asset_block=asset_block,
            genre_rhythm=style_rhythm,
            **seg_static,
            **segment_budget(chunk_text, model),
        )

    chunk_chars = settings.SHOT_SPLIT_CHUNK_CHARS
    logger.info(f"[分镜] 模板 {len(tpl)} 字, prompt_id={data.prompt_id or '默认'}, "
                f"视频模型 {model['name']}（每段 {seg_static['segment_seconds']} 秒），分块上限 {chunk_chars} 字")
    uid = str(user["_id"])

    try:
        logger.info("[分镜] 开始调用大模型拆分镜...")
        items, stats = await split_in_chunks(
            llm, novel, render, chunk_chars,
            on_progress=lambda i, n: set_progress(uid, data.project_id, i, n),
            char_names=char_names, prop_names=prop_names,
        )
        if any(is_segment(x) for x in items):
            fields_list, notes = build_segments(items, model, char_names, prop_names)
            notes = stats["notes"] + notes
            if char_names:
                for f in fields_list:
                    for ln in f["lines"]:
                        if ln["kind"] == "onscreen" and ln["speaker"] not in char_names:
                            notes.append(f"{ln['speaker']} 不在角色资产里却有画内台词（没有参考图，视频里对不上脸）")
            for t in unsourced_lines(fields_list, novel):
                notes.append(f"原文里找不到这句台词（可能是模型补写的）：{t}")
            notes = list(dict.fromkeys(notes))
            for n in notes:
                logger.warning(f"[分镜] 代码兜底：{n}")
            logger.info(f"[分镜] {stats['chunks']} 块共返回 {len(items)} 个视频段，校正后 {len(fields_list)} 段")
        else:
            fields_list, notes = build_legacy_shots(items, char_names, prop_names), []
            logger.info(f"[分镜] 模型返回旧格式 {len(items)} 个镜头，校正后 {len(fields_list)} 个")

        # 批量插入：追加到已有镜头之后，镜号接着往下编（原来每次都从 1 开始，重拆后镜号重复，
        # 视频进度、文件名、剪映排序都按镜号区分，会串）
        if fields_list:
            set_filter = {"$in": [target_set_id, None]} if target_set_id else None
            last = await db.shots.find(
                {"project_id": data.project_id, "user_id": str(user["_id"]), "video_set_id": set_filter},
                {"shot_no": 1},
            ).sort("shot_no", -1).limit(1).to_list(1)
            base_no = int(last[0].get("shot_no") or 0) if last else 0
            shot_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "video_set_id": target_set_id or None,
                    "shot_no": base_no + idx + 1,
                    **fields,
                    "img_path": None,
                    "audio_path": None,
                }
                for idx, fields in enumerate(fields_list)
            ]
            await db.shots.insert_many(shot_docs)
            logger.info(f"[分镜] 已落库 {len(shot_docs)} 条分镜到项目 {data.project_id}")
            for d in shot_docs:
                d.pop("_id", None)

        return ResponseModel(
            message=f"成功拆分{len(fields_list)}个镜头",
            data={"count": len(fields_list), "shots": fields_list, "notes": notes, "chunks": stats["chunks"],
                  "format": "segment" if fields_list and fields_list[0].get("lines") else "legacy"}
        )

    except ShotSplitTruncated as e:
        logger.error(f"[分镜] 拆分失败：{e}")
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[分镜] 拆分失败: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分镜拆分失败: {str(e)}")
    finally:
        clear_progress(uid, data.project_id)


@router.get("/split/progress")
async def split_progress(project_id: str, user: dict = Depends(get_current_user)):
    """拆分镜进度（长文分块时第几块 / 共几块）；没有进行中的拆分返回 data=null。"""
    return ResponseModel(data=get_progress(str(user["_id"]), project_id))


def _as_segment(item: dict) -> dict:
    """模型偶尔在视频段里混一条旧格式（只有 text + character_name），转成单句段。"""
    if is_segment(item) or not (item.get("text") or "").strip():
        return item
    speaker = item.get("character_name") or NARRATOR
    return {**item, "lines": [{"speaker": speaker, "text": item["text"],
                               "kind": "narration" if speaker == NARRATOR else "onscreen"}]}


def build_segments(items: list, model: dict, char_names: set, prop_names: set) -> tuple:
    """视频段格式 → 落库字段列表（含兼容旧字段 text / character_name / prompt / camera）。"""
    fields_list = []
    items, notes = rebalance_segments([_as_segment(x) for x in items], model)
    link_continuity(items)  # 新模板不写承接：重新装段后按上一段尾态补
    for item in items:
        segs, n = normalize_segment(item, model)
        notes.extend(n)
        for seg in segs:
            beats = seg["beats"]
            first = beats[0] if beats else {}
            fields_list.append({
                **legacy_fields(seg["lines"]),
                "lines": seg["lines"],
                "beats": beats,
                "duration": float(seg["duration"]),
                "fill_rate": seg["fill_rate"],
                "model_key": model["key"],
                "mood": str(seg.get("mood") or ""),
                "prompt": seg.get("image_prompt") or seg.get("prompt") or "",
                "neg_prompt": seg.get("neg_prompt", "") or "",
                "video_prompt": seg.get("video_prompt", "") or "",
                "camera": "，".join(x for x in (first.get("shot_size"), first.get("move")) if x)
                          or str(seg.get("camera") or ""),
                "scene": seg.get("scene", "") or "",
                "positions": seg.get("positions", "") or "",
                "continuity": seg.get("continuity", "") or "",
                "tail": seg.get("tail", "") or "",
                "characters": _name_list(seg.get("characters"), char_names),
                "props": _name_list(seg.get("props"), prop_names),
                "split_by_code": bool(seg.get("split_by_code") or seg.get("rebalanced")),
            })
    return fields_list, notes


def build_legacy_shots(shots: list, char_names: set, prop_names: set) -> list:
    """旧格式（一镜一声，用户自定义旧模板产出）：沿用原来的校正逻辑。"""
    raw_count = len(shots)
    shots = split_mixed_voice(shots, char_names)
    if len(shots) != raw_count:
        logger.info(f"[分镜] 拆开旁白/台词混合镜头: {raw_count} → {len(shots)}")
    return [
        {
            "text": shot.get("text", ""),
            "prompt": shot.get("prompt", ""),
            "neg_prompt": shot.get("neg_prompt", ""),
            "duration": normalize_duration(shot.get("duration"), shot.get("text", "")),
            "camera": shot.get("camera", ""),
            "character_name": shot.get("character_name"),
            "video_prompt": shot.get("video_prompt", "") or "",
            "scene": shot.get("scene", "") or "",
            "positions": shot.get("positions", "") or "",
            "characters": _name_list(shot.get("characters"), char_names),
            "props": _name_list(shot.get("props"), prop_names),
        }
        for shot in shots
    ]


@router.post("")
async def create_shot(data: ShotCreate, user: dict = Depends(get_current_user)):
    """创建分镜"""
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
    
    shot_doc = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "shot_no": data.shot_no,
        "text": data.text,
        "prompt": data.prompt,
        "neg_prompt": data.neg_prompt,
        "duration": data.duration,
        "character_name": data.character_name,
        "img_path": None,
        "audio_path": None
    }
    
    result = await db.shots.insert_one(shot_doc)
    
    return ResponseModel(
        message="分镜创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.get("")
async def list_shots(project_id: str, video_set_id: str = "", user: dict = Depends(get_current_user)):
    """获取分镜列表"""
    db = get_db()

    query = {
        "user_id": str(user["_id"]),
        "project_id": project_id
    }
    if video_set_id:
        # 同时包含指定分组内、以及尚未绑定分组的分镜，避免未分组分镜被过滤掉
        query["$or"] = [
            {"video_set_id": video_set_id},
            {"video_set_id": None}  # 匹配字段缺失或为 null（拆分镜时未分组会写 null）
        ]

    cursor = db.shots.find(query).sort("shot_no", 1)

    shots = await cursor.to_list(length=500)

    # 预加载角色/场景/道具
    project = await db.projects.find_one({"_id": ObjectId(project_id)}) if ObjectId.is_valid(project_id) else None
    static_dir = FileUtil.get_static_dir()
    chars = await db.characters.find({"project_id": project_id}).to_list(None)
    scenes = await db.scenes.find({"project_id": project_id}).to_list(None)
    props = await db.props.find({"project_id": project_id}).to_list(None)

    result = []
    for s in shots:
        # 计算关联资产
        text = (s.get("text", "") or "") + " " + (s.get("prompt", "") or "") + " " + (s.get("video_prompt", "") or "")
        assets = []
        if s.get("img_path"):
            assets.append({"type": "分镜参考", "name": "画面", "img": s["img_path"]})
        for ch in chars:
            if ch.get("name") in text and ch.get("image_path"):
                assets.append({"type": "角色", "name": ch["name"], "img": ch["image_path"]})
        for sc in scenes:
            if sc.get("name") in text and sc.get("image_path"):
                assets.append({"type": "场景", "name": sc["name"], "img": sc["image_path"]})
        for pr in props:
            if pr.get("name") in text:
                img = pr.get("image_path") or pr.get("img_path")
                if img:
                    assets.append({"type": "道具", "name": pr["name"], "img": img})

        info = ShotInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            shot_no=s["shot_no"],
            text=s.get("text") or "",
            prompt=s.get("prompt"),
            neg_prompt=s.get("neg_prompt"),
            camera=s.get("camera"),
            duration=s.get("duration"),
            video_prompt=s.get("video_prompt"),
            scene=s.get("scene"),
            positions=s.get("positions"),
            characters=s.get("characters"),
            props=s.get("props"),
            video_path=s.get("video_path"),
            img_path=s.get("img_path"),
            audio_path=s.get("audio_path"),
            character_name=s.get("character_name"),
            lines=s.get("lines"),
            beats=s.get("beats"),
            mood=s.get("mood"),
            model_key=s.get("model_key"),
            continuity=s.get("continuity"),
            tail=s.get("tail"),
            speech_seconds=round(sum(speech_seconds(ln.get("text") or "") for ln in s["lines"]), 1)
            if s.get("lines") else None,
            fill_rate=fill_rate(s["lines"], s.get("duration")) if s.get("lines") else None,
        )
        extra = {"assets": assets}
        if s.get("lines"):
            # 发给视频模型的完整提示词预览：与生成时同一套参考图顺序和组装逻辑
            from api.video import video_task_params
            model = get_video_model(video_task_params(s, project)["model_key"])
            refs = filter_refs(collect_refs(s, chars, scenes, props, static_dir), model)
            extra["final_video_prompt"] = assemble_video_prompt(s, refs)
            extra["prompt_warnings"] = speaker_warnings(s, refs)
        result.append({**info.dict(), **extra})

    return result


@router.put("/{shot_id}")
async def update_shot(
    shot_id: str,
    data: ShotUpdate,
    user: dict = Depends(get_current_user)
):
    """更新分镜"""
    db = get_db()
    
    try:
        obj_id = ObjectId(shot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    # 检查权限
    shot = await db.shots.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 构建更新数据
    update_data = {}
    if data.shot_no is not None:
        update_data["shot_no"] = data.shot_no
    if data.text is not None:
        update_data["text"] = data.text
    if data.prompt is not None:
        update_data["prompt"] = data.prompt
    if data.neg_prompt is not None:
        update_data["neg_prompt"] = data.neg_prompt
    if data.video_prompt is not None:
        update_data["video_prompt"] = data.video_prompt
    if data.character_name is not None:
        update_data["character_name"] = data.character_name
    for field in ("camera", "duration", "scene", "positions", "characters", "props"):
        value = getattr(data, field)
        if value is not None:
            update_data[field] = value
    if data.img_path is not None:
        update_data["img_path"] = data.img_path
    for field in ("mood", "continuity", "tail"):
        value = getattr(data, field)
        if value is not None:
            update_data[field] = value

    message = "分镜更新成功"
    # 视频段：改了逐句台词 / 小镜头 / 时长 → 重新校正每句起止，并同步兼容字段 text / character_name
    if data.lines is not None or (shot.get("lines") and (data.beats is not None or data.duration is not None)):
        model = get_video_model(shot.get("model_key"))
        merged = {
            "lines": data.lines if data.lines is not None else shot.get("lines") or [],
            "beats": data.beats if data.beats is not None else shot.get("beats") or [],
            "duration": data.duration if data.duration is not None else shot.get("duration"),
        }
        fixed = retime_segment(merged, model)
        overflow = fixed.pop("overflow")
        update_data.update(fixed)
        if not fixed["lines"]:
            update_data["character_name"] = NARRATOR
        if overflow:
            message = f"已保存，但本段台词朗读超过 {model['max_duration']} 秒，建议删减或挪到相邻段"

    if update_data:
        await db.shots.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

    return ResponseModel(message=message, data={k: v for k, v in update_data.items()
                                                if k in ("lines", "beats", "duration", "fill_rate",
                                                         "text", "character_name")})


@router.delete("/{shot_id}")
async def delete_shot(shot_id: str, user: dict = Depends(get_current_user)):
    """删除分镜"""
    db = get_db()
    
    try:
        obj_id = ObjectId(shot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的分镜ID")
    
    # 检查权限
    shot = await db.shots.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 删除关联的图片和音频文件
    if shot.get("img_path"):
        FileUtil.delete_file(shot["img_path"])
    if shot.get("audio_path"):
        FileUtil.delete_file(shot["audio_path"])
    
    await db.shots.delete_one({"_id": obj_id})
    
    return ResponseModel(message="分镜删除成功")
