"""资产提取去重：重复提取时，同名的角色、场景、道具并到已有记录，不再新增一条。

原来每提取一次就整批插入，同一个“沈砚”会出现两三条，拆分镜绑定资产时不知道用哪条，参考图也各出各的。
合并的原则是不动用户已有的东西：
- 已有记录里填过的字段（长相、描述、音色…）不覆盖，只补空着的；
- 图片（image_path）永远不动；
- 形态、视角这类列表：只追加名字没出现过的条目，已有条目原样保留。
"""
from typing import Dict, List, Tuple

LIST_FIELDS = ("forms", "views")            # 角色的形态、场景的视角：按条目名追加
PROTECTED = ("_id", "user_id", "project_id", "name", "image_path", "img_path", "create_time")


def norm_name(name) -> str:
    return "".join(str(name or "").split())


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def merge_doc(existing: dict, new: dict) -> dict:
    """把新提取的一条并进已有记录，返回要更新的字段（没有变化返回空字典）。"""
    update: Dict = {}
    for key, value in new.items():
        if key in PROTECTED or _empty(value):
            continue
        if key in LIST_FIELDS and isinstance(value, list):
            have = existing.get(key) if isinstance(existing.get(key), list) else []
            names = {norm_name(x.get("name")) for x in have if isinstance(x, dict)}
            extra = [x for x in value if isinstance(x, dict) and norm_name(x.get("name")) not in names]
            # 已有记录没有形态而新提取的有：整个补上；都有：只追加新名字的
            if extra and (have or _empty(existing.get(key))):
                update[key] = list(have) + extra
        elif _empty(existing.get(key)):
            update[key] = value
    return update


def plan_merge(existing: List[dict], docs: List[dict]) -> Tuple[List[dict], List[Tuple[dict, dict]], int]:
    """决定哪些新增、哪些合并。返回 (要插入的, [(已有记录, 要更新的字段)], 完全重复而跳过的条数)。

    同一批里重名的也只留第一条，后面的并进去。"""
    by_name = {norm_name(d.get("name")): d for d in existing if norm_name(d.get("name"))}
    # 合并重复角色时记下的别名也认：再提取出“白衣阴冷男子”时并回已有的“白衣男子”，不重新冒出来
    for d in existing:
        for alias in d.get("aliases") or []:
            by_name.setdefault(norm_name(alias), d)
    inserts: List[dict] = []
    pending: Dict[str, dict] = {}
    updates: Dict[str, Tuple[dict, dict]] = {}
    skipped = 0
    for doc in docs:
        key = norm_name(doc.get("name"))
        if not key:
            continue
        if key in by_name:
            base = by_name[key]
            merged_view = {**base, **(updates[key][1] if key in updates else {})}
            change = merge_doc(merged_view, doc)
            if change:
                prev = updates[key][1] if key in updates else {}
                updates[key] = (base, {**prev, **change})
            else:
                skipped += 1
        elif key in pending:
            change = merge_doc(pending[key], doc)
            pending[key].update(change)
            skipped += 0 if change else 1
        else:
            pending[key] = doc
            inserts.append(doc)
    return inserts, list(updates.values()), skipped


async def upsert_assets(collection, project_id: str, docs: List[dict]) -> Dict[str, int]:
    """把一批新提取的资产写进集合：同名合并，其余新增。返回 {"added", "merged", "skipped"}。"""
    if not docs:
        return {"added": 0, "merged": 0, "skipped": 0}
    existing = await collection.find({"project_id": project_id}).to_list(None)
    inserts, updates, skipped = plan_merge(existing, docs)
    if inserts:
        await collection.insert_many(inserts)
    for base, change in updates:
        await collection.update_one({"_id": base["_id"]}, {"$set": change})
    return {"added": len(inserts), "merged": len(updates), "skipped": skipped}


def summary(kind: str, r: Dict[str, int]) -> str:
    """“角色新增 2、合并 1”这样的一小段。"""
    bits = [f"新增 {r['added']}"]
    if r["merged"]:
        bits.append(f"并入已有 {r['merged']}")
    if r["skipped"]:
        bits.append(f"已存在 {r['skipped']}")
    return f"{kind}{'、'.join(bits)}"
