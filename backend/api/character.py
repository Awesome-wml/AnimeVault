"""角色管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import (CharacterCreate, CharacterUpdate, CharacterInfo, CharacterExtract, VoiceDesignRequest,
                           ResponseModel)
from db.mongo_client import get_db
from api.auth import get_current_user
from core.voice_design import (design_of, voice_line, normalize_design, fallback_design, pick_cast, design_cast,
                               clashes, narrator_line, SOURCE_AI, SOURCE_RULE, SOURCE_USER)
from core.asset_merge import upsert_assets
from core.llm_factory import build_provider
from core.prompt_registry import build_messages
from core.style_library import build_extract_style_block
from core.character_forms import (character_doc_fields, compose_description, merge_forms_update,
                                  normalize_forms, public_forms, set_form_image)

router = APIRouter(prefix="/api/characters", tags=["角色管理"])


def character_doc(user_id: str, project_id: str, char: dict) -> dict:
    """模型提取的一个角色 → 入库文档（单项提取与全量提取共用；face / forms / voice 见 core/character_forms）。"""
    fields = character_doc_fields(char)
    return {
        "user_id": user_id,
        "project_id": project_id,
        "name": char.get("name", ""),
        "description": fields["description"],
        "face": fields["face"],
        "forms": fields["forms"],
        "voice": fields["voice"],
        "importance": char.get("importance", "support"),
        "gender": char.get("gender"),
        "age_group": char.get("age_group"),
        "trait": char.get("trait"),
        "voice_name": None,
        "image_path": None,
    }


def character_info(c: dict) -> CharacterInfo:
    return CharacterInfo(
        id=str(c["_id"]),
        user_id=c["user_id"],
        project_id=c["project_id"],
        name=c["name"],
        description=c.get("description"),
        face=c.get("face"),
        forms=public_forms(c),
        voice=c.get("voice"),
        voice_design=design_of(c),
        voice_design_source=c.get("voice_design_source"),
        voice_line=voice_line(c) or None,
        voice_name=c.get("voice_name"),
        image_path=c.get("image_path"),
        importance=c.get("importance"),
        gender=c.get("gender"),
        age_group=c.get("age_group"),
        trait=c.get("trait"),
    )


@router.post("/extract")
async def extract_characters(data: CharacterExtract, user: dict = Depends(get_current_user)):
    """AI提取角色"""
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

    # 获取LLM提供者（可按模型预设覆盖）
    llm = build_provider(user, data.model_id, data.model)

    # 构建提示词：骨架来自 system.json，约束来自 constraints.json，数据运行时填入
    style_block = build_extract_style_block(medium=data.medium, genre=data.genre, style_id=data.style)
    messages = build_messages(
        "character_extract",
        variant=project.get("genre"),
        novel_text=data.novel_text[:5000],
        style_block=style_block,
    )

    try:
        result = await llm.chat_json(messages)
        characters = [c for c in (result.get("characters", []) or []) if isinstance(c, dict) and c.get("name")]

        # 批量插入角色
        if characters:
            char_docs = [character_doc(str(user["_id"]), data.project_id, char) for char in characters]
            await upsert_assets(db.characters, data.project_id, char_docs)   # 同名并入已有记录，不重复新增

        return ResponseModel(
            message=f"成功提取{len(characters)}个角色",
            data={"count": len(characters), "characters": characters}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"角色提取失败: {str(e)}")


@router.post("")
async def create_character(data: CharacterCreate, user: dict = Depends(get_current_user)):
    """创建角色"""
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

    forms = normalize_forms([f.dict() for f in data.forms]) if data.forms else []
    face = (data.face or "").strip()
    description = data.description or compose_description(face, forms[0]["outfit"] if forms else "")
    char_doc = {
        "user_id": str(user["_id"]),
        "project_id": data.project_id,
        "name": data.name,
        "description": description,
        "face": face or None,
        "forms": forms,
        "voice": data.voice,
        "voice_design": normalize_design(data.voice_design),
        "voice_design_source": SOURCE_USER if normalize_design(data.voice_design) else None,
        "importance": data.importance,
        "gender": data.gender,
        "age_group": data.age_group,
        "trait": data.trait,
        "voice_name": data.voice_name,
        "image_path": None
    }

    result = await db.characters.insert_one(char_doc)

    return ResponseModel(
        message="角色创建成功",
        data={"id": str(result.inserted_id)}
    )


@router.post("/voice-design")
async def design_voices(data: VoiceDesignRequest, user: dict = Depends(get_current_user)):
    """AI 设计音色：把全体角色放在一起定声音（同场的人要分得开），顺带定旁白的声音。

    手改过的角色不动；AI 设计过的只有 overwrite 才重做；模型失败或漏掉的角色按年龄气质给一份基础设定。
    还没绑配音音色的角色，按新的声音设定从内置音色库里挑一个最接近的。
    """
    from core.voice_matcher import match_voices
    db = get_db()
    uid = str(user["_id"])
    try:
        project = await db.projects.find_one({"_id": ObjectId(data.project_id), "user_id": uid})
    except Exception:
        raise HTTPException(status_code=400, detail="无效的项目ID")
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    chars = await db.characters.find({"user_id": uid, "project_id": data.project_id}).to_list(length=1000)
    if not chars:
        raise HTTPException(status_code=400, detail="该项目没有角色，请先提取角色")

    todo = pick_cast(chars, overwrite=data.overwrite)
    designed, narrator, note = {}, "", ""
    if todo:
        llm = build_provider(user, data.model_id, data.model)
        designed, narrator, note = await design_cast(llm, chars, todo, novel=project.get("novel_content") or "",
                                                     variant=project.get("genre"))
    by_ai = by_rule = 0
    for c in chars:
        name = str(c.get("name"))
        if name in designed:
            design, source = designed[name], SOURCE_AI
            by_ai += 1
        elif not design_of(c):          # 模型没给、或没排进这一批的：先给基础设定，不留空
            design, source = fallback_design(c), SOURCE_RULE
            by_rule += 1
        else:
            continue
        c["voice_design"], c["voice_design_source"] = design, source
        await db.characters.update_one({"_id": c["_id"]}, {"$set": {"voice_design": design, "voice_design_source": source}})
    # 旁白：作品没设过才用模型给的
    if narrator and not project.get("narrator_voice"):
        project["narrator_voice"] = narrator
        await db.projects.update_one({"_id": project["_id"]}, {"$set": {"narrator_voice": narrator}})
    # 配音音色库：没绑过的按声音设定挑最接近的
    unbound = [c for c in chars if not c.get("voice_name")]
    used = {c["voice_name"] for c in chars if c.get("voice_name")}
    for a in match_voices(unbound, used) if unbound else []:
        if a.get("voice"):
            await db.characters.update_one({"user_id": uid, "project_id": data.project_id, "name": a["name"]},
                                           {"$set": {"voice_name": a["voice"]}})
            next(c for c in chars if c.get("name") == a["name"])["voice_name"] = a["voice"]

    parts = [f"为 {by_ai} 个角色设计了声音" if by_ai else "", f"{by_rule} 个按年龄和气质给了基础设定" if by_rule else ""]
    message = "，".join(x for x in parts if x) or "所有角色都已有声音设定（手改过的不会被覆盖）"
    return ResponseModel(message=message, data={
        "designed": by_ai, "fallback": by_rule, "note": note, "warnings": clashes(chars),
        "narrator_voice": narrator_line(project),
        "characters": [{"name": c.get("name"), "voice_design": design_of(c), "voice_line": voice_line(c),
                        "voice_design_source": c.get("voice_design_source"), "voice_name": c.get("voice_name")}
                       for c in chars],
    })


@router.get("", response_model=List[CharacterInfo])
async def list_characters(project_id: str, user: dict = Depends(get_current_user)):
    """获取角色列表"""
    db = get_db()

    cursor = db.characters.find({
        "user_id": str(user["_id"]),
        "project_id": project_id
    })
    characters = await cursor.to_list(length=100)

    return [character_info(c) for c in characters]


@router.put("/{character_id}")
async def update_character(
    character_id: str,
    data: CharacterUpdate,
    user: dict = Depends(get_current_user)
):
    """更新角色"""
    db = get_db()

    try:
        obj_id = ObjectId(character_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的角色ID")

    # 检查权限
    character = await db.characters.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 构建更新数据
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if data.voice_name is not None:
        update_data["voice_name"] = data.voice_name
    if data.image_path is not None:
        # 旧接口改图 = 改第一形态的图
        update_data.update(set_form_image(character, 0, data.image_path))
    for field in ("importance", "gender", "age_group", "trait", "face", "voice"):
        value = getattr(data, field)
        if value is not None:
            update_data[field] = value
    if data.voice_design is not None:
        # 手改的声音设定记为用户设定：之后再点 AI 设计也不覆盖；传 {} 清空
        design = normalize_design(data.voice_design)
        update_data["voice_design"] = design
        update_data["voice_design_source"] = SOURCE_USER if design else None
    if data.forms is not None:
        forms = merge_forms_update(character, [f.dict() for f in data.forms])
        if not forms:
            raise HTTPException(status_code=400, detail="至少保留一个形态")
        update_data["forms"] = forms
        # 第一形态的图与旧字段 image_path 互为镜像
        update_data["image_path"] = forms[0].get("image_path")

    if update_data:
        await db.characters.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

    return ResponseModel(message="角色更新成功")


@router.delete("/{character_id}")
async def delete_character(character_id: str, user: dict = Depends(get_current_user)):
    """删除角色"""
    db = get_db()

    try:
        obj_id = ObjectId(character_id)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的角色ID")

    # 检查权限
    character = await db.characters.find_one({
        "_id": obj_id,
        "user_id": str(user["_id"])
    })

    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    await db.characters.delete_one({"_id": obj_id})

    return ResponseModel(message="角色删除成功")
