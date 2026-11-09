"""角色管理API"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from typing import List

from models.schema import CharacterCreate, CharacterUpdate, CharacterInfo, CharacterExtract, ResponseModel
from db.mongo_client import get_db
from api.auth import get_current_user
from core.prompt_tpl import CHARACTER_EXTRACT_PROMPT
from core.llm_factory import build_provider, resolve_prompt, safe_format
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

    # 构建提示词（注入风格，真人类风格追加面部真实质感要求；可按提示词ID覆盖）
    style_block = build_extract_style_block(data.style) if data.style else ""
    tpl = resolve_prompt(data.prompt_id, "character_extract", CHARACTER_EXTRACT_PROMPT, category=project.get("genre"))
    prompt = safe_format(
        tpl,
        novel_text=data.novel_text[:5000],
        style_block=style_block
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        result = await llm.chat_json(messages)
        characters = [c for c in (result.get("characters", []) or []) if isinstance(c, dict) and c.get("name")]

        # 批量插入角色
        if characters:
            char_docs = [character_doc(str(user["_id"]), data.project_id, char) for char in characters]
            await db.characters.insert_many(char_docs)

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
