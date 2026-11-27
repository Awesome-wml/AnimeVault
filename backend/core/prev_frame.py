"""“承接上一条”首帧参考的取数口径（生成与预览共用）。

镜号在每一集里都从 1 开始，所以找“上一段”必须限定在同一集（video_set_id）里；
尾帧图文件名用镜头 _id，不同作品、不同集同号镜头不会互相覆盖。

接缝类型为“切镜”（joint = cut）的段不承接上一段尾帧：换场、反打、换角度时用角色/场景图重新锚定外观。
"""

# 截上一段倒数这么多秒的一帧做本段首帧；导出剪映时上一段末尾同样剪掉这么多，接缝处不重演
PREV_FRAME_OFFSET_SECONDS = 0.5
CUT_REASON = "本段为切镜，不承接上一段尾帧"


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


def plan_chains(shots: list, use_prev_frame: bool = True) -> dict:
    """一批要生成的分镜按“续接链”排好：同一链里后一段要等前一段成片（才能截它的尾帧），不同链之间互不依赖。

    shots：同一集里要生成的分镜（含 shot_no、joint）。一段接在前一段后面的条件：要用尾帧、本段不是切镜、
    镜号减一的那段也在这一批里。返回 {"chains": [[shot, …], …], "pred": {镜号: 链上前一段镜号}}，
    链按首段镜号排序，链内按镜号。
    """
    from core.shot_timing import is_cut   # 避免循环引用

    by_no = {int(s.get("shot_no") or 0): s for s in shots}
    pred = {}
    for no, s in by_no.items():
        if use_prev_frame and not is_cut(s) and (no - 1) in by_no:
            pred[no] = no - 1
    chains, seen = [], set()
    for no in sorted(by_no):
        if no in seen or no in pred:
            continue
        chain, cur = [], no
        while cur in by_no and cur not in seen:
            chain.append(by_no[cur])
            seen.add(cur)
            nxt = cur + 1
            cur = nxt if pred.get(nxt) == cur else None
        chains.append(chain)
    return {"chains": chains, "pred": pred}


def waves(chains: list) -> list:
    """把续接链拆成先后几波：第 k 波 = 每条链的第 k 段。同一波里的段互不依赖，可以并行。"""
    out = []
    depth = max((len(c) for c in chains), default=0)
    for k in range(depth):
        out.append([c[k] for c in chains if len(c) > k])
    return out
