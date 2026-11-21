"""成片回看：视频下好后检测实际切了几个镜头，和提示词里写的小镜头对一遍。

为什么要有：提示词写了 3 个小镜头，成片可能切 4 个（模型撑不住长镜头自己补切），也可能少切、或时长不对。
这些只有看成片才知道。每条成片都自动对一遍，偏差写回分镜（shots.review），在分镜列表的提示里显示；
积累下来就知道哪种写法、哪个上限模型真的照做——换模型、改能力表（core/prompt_profiles）时拿它当依据。

只用 ffmpeg 的场景切换检测（scene 滤镜），不调任何模型；检测的是硬切，叠化和镜头内运动不算。
"""
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from core.ffmpeg_tool import ffmpeg_exe, probe_seconds

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = 0.3      # ffmpeg scene 分数阈值：0.3 对硬切稳定，镜头内运动一般到不了
CUT_TOLERANCE = 0.8        # 实际切点与计划切点相差这么多秒以内算对上（模型的切点不会卡得很准）
MIN_CUT_GAP = 0.5          # 相距不到这么久的两个切点算一个（闪白、快速运动的连续误报）
DURATION_TOLERANCE = 0.6   # 成片时长与段时长相差超过这么多秒算时长不符
_PTS = re.compile(r"pts_time:([0-9.]+)")


def detect_cuts(path, threshold: float = SCENE_THRESHOLD) -> List[float]:
    """视频里的硬切时间点（秒，升序）。ffmpeg 失败抛 RuntimeError。"""
    cmd = [ffmpeg_exe(), "-hide_banner", "-i", str(path), "-an",
           "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 场景检测失败: {(r.stderr or '')[-200:]}")
    cuts: List[float] = []
    for m in _PTS.finditer(r.stderr or ""):
        t = round(float(m.group(1)), 2)
        if t > 0.2 and (not cuts or t - cuts[-1] >= MIN_CUT_GAP):
            cuts.append(t)
    return cuts


def planned_cuts(beats: list) -> List[float]:
    """提示词里写的切点：第 2 个小镜头起每个的起点。"""
    out = []
    for b in (beats or [])[1:]:
        if isinstance(b, dict) and b.get("start") is not None:
            out.append(round(float(b["start"]), 2))
    return out


def compare_cuts(planned: List[float], actual: List[float], tolerance: float = CUT_TOLERANCE) -> dict:
    """计划切点与实际切点一一配对（各用一次，按时间就近）。返回对上的、多切的、没切的。"""
    left = list(actual)
    matched, missing = [], []
    for p in planned:
        near = min(left, key=lambda a: abs(a - p), default=None)
        if near is not None and abs(near - p) <= tolerance:
            matched.append({"planned": p, "actual": near})
            left.remove(near)
        else:
            missing.append(p)
    return {"matched": matched, "extra": left, "missing": missing}


def _longest_gap(points: List[float], duration: float) -> float:
    edges = [0.0] + sorted(points) + [duration]
    return max((b - a for a, b in zip(edges, edges[1:])), default=duration)


def review(beats: list, cuts: List[float], video_seconds: Optional[float], planned_seconds: Optional[float]) -> dict:
    """把检测结果整理成结论。纯函数，方便测试。"""
    plan = planned_cuts(beats)
    cmp = compare_cuts(plan, cuts)
    notes = []
    n_plan, n_real = len(plan) + 1, len(cuts) + 1
    if cmp["extra"]:
        at = "、".join(f"{t:g}" for t in cmp["extra"])
        notes.append(f"成片回看：提示词写了 {n_plan} 个小镜头，成片切了 {n_real} 个；多切在 {at} 秒"
                     f"（多半是某个小镜头太长，模型自己补了一镜）")
    if cmp["missing"]:
        at = "、".join(f"{t:g}" for t in cmp["missing"])
        notes.append(f"成片回看：计划在 {at} 秒切镜，成片没有切（两个小镜头被拍成了一个）")
    if video_seconds and planned_seconds and abs(video_seconds - float(planned_seconds)) > DURATION_TOLERANCE:
        notes.append(f"成片回看：成片 {video_seconds:.1f} 秒，段时长是 {float(planned_seconds):g} 秒")
    longest = round(_longest_gap(cuts, video_seconds or float(planned_seconds or 0)), 1) if (video_seconds or planned_seconds) else None
    return {"planned_cuts": plan, "actual_cuts": cuts, "extra": cmp["extra"], "missing": cmp["missing"],
            "matched": len(cmp["matched"]), "video_seconds": video_seconds, "longest_shot_seconds": longest,
            "ok": not cmp["extra"] and not cmp["missing"], "notes": notes}


def review_video(shot: dict, static_dir) -> Optional[dict]:
    """对一条分镜的成片做回看；没有成片或文件不在返回 None，ffmpeg 出错返回带 error 的结果（不抛）。"""
    rel = shot.get("video_path")
    if not rel:
        return None
    f = Path(rel) if Path(rel).is_absolute() else Path(static_dir) / rel
    if not f.exists():
        return None
    try:
        cuts = detect_cuts(f)
        seconds = round(probe_seconds(f), 2)
    except Exception as e:            # 回看是锦上添花，不能因为它让出片流程失败
        logger.warning("成片回看失败 %s: %s", f, e)
        return {"error": str(e)[:200], "notes": [], "ok": None, "video_path": rel}
    out = review(shot.get("beats") or [], cuts, seconds, shot.get("duration"))
    out["video_path"] = rel            # 换了成片（重新生成）时据此判断回看结果是否过期
    return out


def summarize(reviews: list) -> dict:
    """一批回看结果的汇总：多少条照着提示词切了、多切/少切各多少、成片里最长的一个镜头多长。"""
    done = [r for r in reviews if isinstance(r, dict) and r.get("ok") is not None]
    longest = [r["longest_shot_seconds"] for r in done if r.get("longest_shot_seconds")]
    return {"reviewed": len(done), "as_planned": sum(1 for r in done if r["ok"]),
            "with_extra_cuts": sum(1 for r in done if r.get("extra")),
            "with_missing_cuts": sum(1 for r in done if r.get("missing")),
            "longest_shot_seconds": max(longest) if longest else None}
