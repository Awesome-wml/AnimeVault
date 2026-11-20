"""“承接上一条”首帧参考的取数口径（生成与预览共用）。

镜号在每一集里都从 1 开始，所以找“上一段”必须限定在同一集（video_set_id）里；
尾帧图文件名用镜头 _id，不同作品、不同集同号镜头不会互相覆盖。
"""


def prev_shot_filter(shot: dict) -> dict:
    """上一段分镜的查询条件：同作品、同一集、镜号减一。

    video_set_id 为 None/缺失（未分组的旧数据）时，Mongo 的 {"video_set_id": None}
    同样匹配字段缺失，与拆分镜写入 null 的口径一致。
    """
    return {
        "project_id": shot["project_id"],
        "video_set_id": shot.get("video_set_id") or None,
        "shot_no": int(shot.get("shot_no") or 0) - 1,
    }


def prev_frame_name(shot: dict) -> str:
    """本段的“上一段尾帧”截图文件名（放在 static/images 下）。"""
    sid = shot.get("_id") or shot.get("id")
    if sid:
        return f"prev_frame_{sid}.png"
    return f"prev_frame_{shot.get('project_id', 'p')}_{shot.get('video_set_id') or 'none'}_{shot.get('shot_no')}.png"
