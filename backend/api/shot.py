"""分镜管理API"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List
from pathlib import Path

from models.schema import ShotCreate, ShotUpdate, ShotInfo, ShotSplit, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from api.video_set import resolve_set
from core.llm_factory import build_provider
from core.prompt_registry import build_messages, resolve_prompt
from core.shot_timing import (NARRATOR, beat_rhythm_warnings, drop_repeated_lines, fill_rate, is_segment, legacy_fields, normalize_duration,
                              normalize_segment, retime_segment, shot_size_warnings, speech_overflow_warnings,
                              speech_seconds, unsourced_lines)
from core.shot_split import (MAX_SPLIT_CHARS, OUTPUT_TOKENS_PER_CHAR, OUTPUT_TOKENS_PER_SCRIPT_CHAR,
                             ShotSplitTruncated, budget_chunk_chars, link_continuity,
                             split_in_chunks)
from core.sse import run_with_sse
from core.style_suggest import auto_style_if_needed
from core.shot_voice import split_mixed_voice
from core.storyboard import storyboard_body, storyboard_panels
from config.settings import settings
from core.knowledge import plan_for
from core.video_models import get_video_model, segment_budget, segment_params
from core.video_prompt import build_upload_plan, TYPE_CN
from core.asset_binding import collect_bindings
from core.ffmpeg_tool import grab_last_frame
from core.prev_frame import prev_frame_name, prev_shot_filter
from core.script_text import (chunk_scenes, halve_scene_chunk, load_scripts, locate_scene_no, scripts_to_text,
                              voiced_of_text, voiced_text)
from core.style_library import (build_style_block, build_genre_rhythm, build_video_style_line, medium_key,
                                style_mismatch_warnings, style_ref)
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



def _static_rel(path: str, static_dir) -> str:
    """绝对路径 → static 下的相对路径（前端按 /static/<相对路径> 显示）。"""
    try:
        return str(Path(path).resolve().relative_to(Path(static_dir).resolve()))
    except ValueError:
        return path


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

    # 新建时没选风格的作品：第一次用到风格前先按正文自动识别（core/style_suggest.py），之后全链路照它出图出视频
    await auto_style_if_needed(db, project, llm, data.novel_paragraph)
    # 读取项目风格，注入到分镜拆分提示词（可按提示词ID覆盖）
    style = style_ref(project)  # 媒介 + 题材（旧项目只有 style 时自动映射）
    style_block = build_style_block(**style)

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

    # 拆分依据：有本集剧本场次用场次文本（按场次分块），没有则用本集小说原文
    scripts = await load_scripts(db, data.project_id, target_set_id)
    if scripts:
        novel = scripts_to_text(scripts).strip()
        source_label = f"剧本 {len(scripts)} 场"
    else:
        novel = (data.novel_paragraph or "").strip()
        if not novel:
            set_doc = await resolve_set(db, data.project_id, target_set_id, str(user["_id"]))
            if set_doc:
                novel = (set_doc.get("novel_content") or "").strip()
        source_label = "小说原文"
    logger.info(f"[分镜] 拆分依据: {source_label}（{len(novel)} 字）")
    if len(novel) > MAX_SPLIT_CHARS:
        what = "剧本" if scripts else "小说"
        raise HTTPException(status_code=400, detail=f"{what}超过 {MAX_SPLIT_CHARS} 字，请分集拆分镜")

    # 有剧本用剧本版，无剧本用小说版；模板来自注册表文件
    shot_key = "split_shots_script" if scripts else "split_shots"
    prompt_key, prompt_variant = resolve_prompt(data.prompt_id, shot_key)
    style_rhythm = build_genre_rhythm(**style)
    seg_static = segment_params(model)

    def render(chunk_text: str, note: str) -> list:
        """每块都注入资产清单、风格与题材节奏；段数预算按本块朗读量算。返回 messages。"""
        return build_messages(
            prompt_key,
            variant=prompt_variant if prompt_variant is not None else project.get("genre"),
            novel_paragraph=chunk_text,
            chunk_note=note,
            style_block=style_block,
            asset_block=asset_block,
            genre_rhythm=style_rhythm,
            **seg_static,
            # 段数预算按本块要配音的台词算（剧本块不算场头、动作和节拍）
            **segment_budget(voiced_of_text(chunk_text) if scripts else chunk_text, model),
        )

    # 每块字数按这个模型单次能输出多少 tokens 算（SHOT_SPLIT_CHUNK_CHARS 只是上限）：
    # 9 字段小镜头的输出约为输入的 8～10 倍 tokens，4000 字一块远超 16384 的输出上限，必然截断
    per_char = OUTPUT_TOKENS_PER_SCRIPT_CHAR if scripts else OUTPUT_TOKENS_PER_CHAR
    budget_fn = getattr(llm, "json_output_budget", None)
    output_budget = budget_fn() if callable(budget_fn) else 16384
    chunk_chars = budget_chunk_chars(output_budget, settings.SHOT_SPLIT_CHUNK_CHARS, per_char)
    chunks = chunk_scenes(scripts, chunk_chars) if scripts else None
    logger.info(f"[分镜] 模板 {shot_key}, prompt_id={data.prompt_id or '默认'}, "
                f"视频模型 {model['name']}（每段 {seg_static['segment_seconds']} 秒），"
                f"输出额度 {output_budget} tokens → 分块上限 {chunk_chars} 字")
    async def build_task(report):
        logger.info("[分镜] 开始调用大模型拆分镜...")

        state = {"chunk": 1, "total": 1}

        async def on_progress(i, n):
            state["chunk"], state["total"] = i, n
            await report(0, chunk=i, total=n)

        async def on_chars(chars):
            await report(chars, chunk=state["chunk"], total=state["total"])

        # 分镜智能体：先通读全文做规划 → 按规划分块、各块带着规划拆 → 每块拆完审一遍（core/shot_agent）
        from core import shot_agent
        from core.shot_split import split_novel_chunks
        plan, plan_msg = None, ""
        work_chunks = chunks
        # 作品知识库：角色、场景、道具的设定和它们之间的关联，三步读同一份（core/knowledge）
        from core.knowledge import knowledge_text
        kb = {"text": knowledge_text(chars, scenes, props, scripts=scripts)}
        if settings.SHOT_SPLIT_PLAN and not scripts:        # 剧本本身已经分好场次，不再另做规划
            plan, plan_msg = await shot_agent.make_plan(llm, novel, "\n".join(x for x in (asset_block, kb["text"]) if x),
                                                        seg_static["segment_seconds"])
            work_chunks = shot_agent.plan_chunks(plan, novel, chunk_chars) or split_novel_chunks(novel, chunk_chars)
            if plan:      # 规划也是知识库的一部分：哪一场有谁，补进场景卡
                kb["text"] = knowledge_text(chars, scenes, props, plan=plan, scripts=scripts)

        def note_extra(index: int) -> str:
            # 每块的说明 = 知识库（设定与关联）+ 全集规划里和这一块有关的部分
            plan_part = shot_agent.plan_note(plan, novel, work_chunks, index) if plan else ""
            return "\n".join(x for x in (kb["text"], plan_part) if x)

        async def reviewer(text, segs, index, opening):
            return await shot_agent.review_chunk(llm, text, segs, note_extra(index), opening=opening)

        items, stats = await split_in_chunks(
            llm, novel, render, chunk_chars,
            on_progress=on_progress, on_chars=on_chars,
            char_names=char_names, prop_names=prop_names, chunks=work_chunks,
            note_extra=note_extra if (plan or kb["text"]) else None,
            reviewer=reviewer if settings.SHOT_SPLIT_REVIEW else None,
            source_of=voiced_of_text if scripts else None,
            halve=halve_scene_chunk if scripts else None,
            tokens_per_char=per_char,
            concurrency=settings.SHOT_SPLIT_CONCURRENCY,
        )
        if any(is_segment(x) for x in items):
            fields_list, notes = build_segments(items, model, char_names, prop_names,
                                                genre=str(project.get("genre") or ""))
            notes = ([plan_msg] if plan_msg else []) + shot_agent.summarize_notes(stats.get("review_notes") or []) \
                + stats["notes"] + notes
            if char_names:
                for f in fields_list:
                    for ln in f["lines"]:
                        if ln["kind"] == "onscreen" and ln["speaker"] not in char_names:
                            notes.append(f"{ln['speaker']} 不在角色资产里却有画内台词（没有参考图，视频里对不上脸）")
            for t in unsourced_lines(fields_list, voiced_text(scripts) if scripts else novel):
                notes.append(f"原文里找不到这句台词（可能是模型补写的）：{t}")
            notes = list(dict.fromkeys(notes))
            for n in notes:
                logger.warning(f"[分镜] 代码兜底：{n}")
            logger.info(f"[分镜] {stats['chunks']} 块共返回 {len(items)} 个视频段，校正后 {len(fields_list)} 段")
        else:
            fields_list, notes = build_legacy_shots(items, char_names, prop_names), []
            logger.info(f"[分镜] 模型返回旧格式 {len(items)} 个镜头，校正后 {len(fields_list)} 个")

        # 剧本拆分：场次号以台词反查为准，模型回填错配的场次号在此被校正；
        # 反查不到（纯动作无台词段）时，再保留模型回填的合法场次号，回填非法则置空。
        if scripts:
            valid = {s.get("scene_no") for s in scripts}
            for f in fields_list:
                lines = f.get("lines") or [{"text": f.get("text")}]
                inferred = locate_scene_no(lines, scripts)
                if inferred is not None:
                    f["scene_no"] = inferred
                elif f.get("scene_no") not in valid:
                    f["scene_no"] = None
        else:
            for f in fields_list:
                f.pop("scene_no", None)

        # 覆盖重拆：模型成功返回后，先清空本集旧分镜，新镜头镜号从 1 重编。
        # 旧镜头的画面/音频/视频引用一并作废；模型调用失败抛错时不会走到这里，旧镜头保留。
        if fields_list:
            del_filter = {"project_id": data.project_id, "user_id": str(user["_id"])}
            del_filter["video_set_id"] = target_set_id or None
            old = await db.shots.delete_many(del_filter)
            logger.info(f"[分镜] 已清空本集旧分镜 {old.deleted_count} 条")
            shot_docs = [
                {
                    "user_id": str(user["_id"]),
                    "project_id": data.project_id,
                    "video_set_id": target_set_id or None,
                    "shot_no": idx + 1,
                    **fields,
                    "img_path": None,
                    "storyboard_path": None,
                    "audio_path": None,
                }
                for idx, fields in enumerate(fields_list)
            ]
            await db.shots.insert_many(shot_docs)
            logger.info(f"[分镜] 已落库 {len(shot_docs)} 条分镜到项目 {data.project_id}")
            if plan:
                # 全集规划存回作品（按集）：它是知识库的一部分，之后出图、重拆、复查都能用同一份
                await db.projects.update_one(
                    {"_id": ObjectId(data.project_id)},
                    {"$set": {f"shot_plans.{target_set_id or 'default'}": plan}})
            for d in shot_docs:
                d.pop("_id", None)

        message = f"成功拆分{len(fields_list)}个镜头"
        payload = {"count": len(fields_list), "shots": fields_list, "notes": notes, "chunks": stats["chunks"], "plan": plan,
                   "format": "segment" if fields_list and fields_list[0].get("lines") else "legacy",
                   "source": "script" if scripts else "novel"}
        return message, payload

    return await run_with_sse(build_task)


def _as_segment(item: dict) -> dict:
    """模型偶尔在视频段里混一条旧格式（只有 text + character_name），转成单句段。"""
    if is_segment(item) or not (item.get("text") or "").strip():
        return item
    speaker = item.get("character_name") or NARRATOR
    return {**item, "lines": [{"speaker": speaker, "text": item["text"],
                               "kind": "narration" if speaker == NARRATOR else "onscreen"}]}


def _scene_no(value):
    """模型回填的场次号 → int；没有或不是数字返回 None。"""
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def build_segments(items: list, model: dict, char_names: set, prop_names: set, genre: str = "") -> tuple:
    """视频段格式 → 落库字段列表（含兼容旧字段 text / character_name / prompt / camera）。
    storyboard_prompt（四格分镜文案）由代码按小镜头拼出，genre 用于光影映射。"""
    fields_list = []
    # 模型返回几段就保留几段：后端不重新装段、不二次分组，只做解析和资产绑定
    items = [_as_segment(x) for x in items]
    notes = []
    notes.extend(drop_repeated_lines(items))  # 相邻段首尾重复的台词只留一处
    link_continuity(items)  # 新模板不写承接：按上一段尾态补
    for item in items:
        notes.extend(item.pop("parse_notes", None) or [])   # R11：伪说话人整句转旁白的提示
        segs, n = normalize_segment(item, model)
        notes.extend(n)
        for seg in segs:
            beats = seg["beats"]
            first = beats[0] if beats else {}
            fields = {
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
                "scene_no": _scene_no(seg.get("scene_no")),
            }
            fields["storyboard_prompt"] = storyboard_body(fields, genre)
            fields_list.append(fields)
    notes.extend(shot_size_warnings(fields_list))  # 景别自检：连续 3 个小镜头同一景别
    notes.extend(speech_overflow_warnings(fields_list))  # 台词装不进段时长
    notes.extend(beat_rhythm_warnings(fields_list))  # 节奏自检：开场钩子过长、单个小镜头超过 8 秒
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
            "scene_no": shot.get("scene_no"),
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
    scripts_query = {"project_id": project_id}
    if video_set_id:
        scripts_query["video_set_id"] = video_set_id
    scripts = await db.scripts.find(scripts_query).to_list(None)
    location_by_scene = {
        sc.get("scene_no"): (sc.get("location") or "") for sc in scripts
    }

    genre = str((project or {}).get("genre") or "")
    style_suffix = build_video_style_line(**style_ref(project))
    cur_key = medium_key(**style_ref(project))
    all_assets = list(chars) + list(scenes) + list(props)
    result = []
    try:      # 有成片还没回看的，放后台逐条检测实际切点，下次刷新时显示
        from api.video import schedule_reviews
        schedule_reviews(db, shots)
    except Exception as e:
        logger.warning("成片回看排队失败: %s", e)
    for s in shots:
        # 关联资产与发给视频模型的提示词：与生成时同一个函数（build_upload_plan），
        # 资产选择与顺序来自 core.asset_binding.collect_bindings，图号 = 上传顺序
        from api.video import video_task_params
        model = get_video_model(video_task_params(s, project)["model_key"])
        plan = build_upload_plan(s, chars, scenes, props, static_dir, model,
                                 scene_location=location_by_scene.get(s.get("scene_no"), ""), genre=genre,
                                 style_suffix=style_suffix,
                             plan=plan_for(project, s.get("video_set_id")))
        assets = [{"type": TYPE_CN[b["asset_type"]], "name": b["name"],
                   "label": b.get("label") or "", "asset_id": b.get("asset_id"),
                   "img": b.get("img"), "form": b.get("form"), "warning": b.get("warning")}
                  for b in collect_bindings(
                      s, chars, scenes, props,
                      scene_location=location_by_scene.get(s.get("scene_no"), ""),
                      scene_no=s.get("scene_no"))]
        # 首帧（上一段尾帧）参考状态：预览不实际截帧，只判断生成时能否挂上
        prev_frame = {"attached": False, "image": None, "reason": None}
        prev_shot = await db.shots.find_one(prev_shot_filter(s))
        if not prev_shot:
            prev_frame["reason"] = "首段无上一段尾帧"
        elif not prev_shot.get("video_path"):
            prev_frame["reason"] = "上一段分镜尚未成片"
        else:
            prev_vid = static_dir / prev_shot["video_path"]
            if not prev_vid.exists():
                prev_frame["reason"] = "上一段成片文件缺失"
            else:
                prev_frame["attached"] = True
                frame_name = prev_frame_name(s)
                frame_path = static_dir / "images" / frame_name
                # 预览即懒截上一段尾帧，生成前就能在页面检查首帧图；已存在则复用
                if not frame_path.exists():
                    grab_last_frame(prev_vid, frame_path)
                if frame_path.exists():
                    prev_frame["image"] = f"images/{frame_name}"
                else:
                    prev_frame["reason"] = "尾帧截帧失败"

        info = ShotInfo(
            id=str(s["_id"]),
            project_id=s["project_id"],
            shot_no=s["shot_no"],
            text=s.get("text") or "",
            scene_no=s.get("scene_no"),
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
            storyboard_path=s.get("storyboard_path"),
            # 四格文案：T-215 之前拆的段没有存，按小镜头现算（不落库）
            storyboard_prompt=(s.get("storyboard_prompt") or storyboard_body(s, genre) or None) if s.get("beats") else None,
            storyboard_panels=storyboard_panels(s) if s.get("beats") else None,
        )
        # 参考图出图时的画风与作品当前媒介不一致：提示词仍以作品媒介为准，这里提示“建议重新出图”
        extra = {"assets": assets, "style_warnings": style_mismatch_warnings(plan["refs"], all_assets, cur_key),
                 "project_medium": cur_key, "prev_frame": prev_frame}
        if s.get("lines"):
            # 发给视频模型的完整提示词预览
            extra["final_video_prompt"] = plan["prompt"]
            warnings = list(plan["warnings"])
            if not prev_frame["attached"]:
                warnings.append(f"本条未带上一段尾帧参考：{prev_frame['reason']}")
            rev = s.get("review") or {}
            if rev.get("video_path") == s.get("video_path"):      # 成片回看的结论（换过成片的旧结论不显示）
                warnings.extend(rev.get("notes") or [])
                extra["review"] = rev
            extra["prompt_warnings"] = warnings
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
    for field in ("mood", "continuity", "tail", "storyboard_prompt", "storyboard_path"):
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
    # 小镜头、站位、人物、道具或情绪变了 → 四格文案按新内容重拼（用户这次没有手改四格文案时）
    if data.storyboard_prompt is None and shot.get("beats") and \
            any(k in update_data for k in ("beats", "positions", "characters", "props", "mood", "scene")):
        project = await db.projects.find_one({"_id": ObjectId(shot["project_id"])}) \
            if ObjectId.is_valid(shot.get("project_id") or "") else None
        update_data["storyboard_prompt"] = storyboard_body({**shot, **update_data},
                                                           str((project or {}).get("genre") or ""))

    if update_data:
        await db.shots.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

    return ResponseModel(message=message, data={k: v for k, v in update_data.items()
                                                if k in ("lines", "beats", "duration", "fill_rate",
                                                         "text", "character_name", "storyboard_prompt")})


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
    if shot.get("storyboard_path"):
        FileUtil.delete_file(shot["storyboard_path"])
    if shot.get("audio_path"):
        FileUtil.delete_file(shot["audio_path"])
    
    await db.shots.delete_one({"_id": obj_id})
    
    return ResponseModel(message="分镜删除成功")
