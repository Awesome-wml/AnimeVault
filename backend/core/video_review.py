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
    # 每个计划内的小镜头：多长、里面有没有被模型自己多切一刀（学“模型撑得住多长的镜头”用）
    edges = [0.0] + plan + [float(video_seconds or planned_seconds or (plan[-1] if plan else 0))]
    beat_stats = [{"seconds": round(b - a, 1), "cut_inside": any(a + CUT_TOLERANCE < x < b - CUT_TOLERANCE for x in cmp["extra"])}
                  for a, b in zip(edges, edges[1:]) if b > a]
    return {"beats": beat_stats,
            "planned_cuts": plan, "actual_cuts": cuts, "extra": cmp["extra"], "missing": cmp["missing"],
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


# ============================================================
# 从回看结果里学：这个视频模型实际撑得住多长的小镜头
# ============================================================
LEARN_MIN_SAMPLES = 4        # 某个时长档至少有这么多个小镜头的样本才下结论
LEARN_MAX_CUT_RATE = 0.25    # 这一档里被多切的比例不超过这个，才算“撑得住”
LEARN_FLOOR = 4.0            # 学出来的上限不低于这个秒数（再短就全是碎镜头了）


def learned_beat_cap(reviews: list, ceiling: float = 8.0) -> Optional[dict]:
    """按一批回看结果算出小镜头时长上限。样本不够返回 None（继续用能力表里的值）。

    做法：把所有计划内的小镜头按时长分档（每 1 秒一档），从短到长看每一档被模型多切的比例；
    第一个“样本够、多切比例超标”的档就是模型撑不住的长度，上限取它的下沿。全都撑得住就不动。
    返回 {"max_beat_seconds", "samples", "evidence"}。
    """
    buckets: dict = {}
    for r in reviews:
        if not isinstance(r, dict) or r.get("ok") is None:
            continue
        for b in r.get("beats") or []:
            try:
                sec = float(b.get("seconds"))
            except (TypeError, ValueError):
                continue
            if sec < LEARN_FLOOR:
                continue
            k = int(sec) if sec == int(sec) else int(sec) + 1          # (4,5] → 5 这一档
            n, cut = buckets.get(k, (0, 0))
            buckets[k] = (n + 1, cut + (1 if b.get("cut_inside") else 0))
    samples = sum(n for n, _ in buckets.values())
    for k in sorted(buckets):
        n, cut = buckets[k]
        if n >= LEARN_MIN_SAMPLES and cut / n > LEARN_MAX_CUT_RATE:
            cap = max(float(k - 1), LEARN_FLOOR)
            if cap >= ceiling:
                return None
            return {"max_beat_seconds": cap, "samples": samples,
                    "evidence": f"{k - 1}～{k} 秒的小镜头 {n} 个里有 {cut} 个被模型自己多切了一刀"}
    return None


# ============================================================
# 看图检查内容（可选，默认不做）：每个小镜头抽一帧，交给看图模型对照描述检查
# ============================================================
# 切点检测只知道“切了几刀”，不知道画面对不对。这里每个小镜头取中间一帧，问看图模型三件事：
# 画面里有几个人、有没有出现文字或字幕、和这一镜的描述是否相符。需要一个能看图的对话模型（如智谱 GLM-4.5V），
# 每条成片多一次模型调用；没有连真实模型验证过，所以只在显式指定看图模型时才跑。
VISION_FRAME_WIDTH = 512
VISION_MAX_FRAMES = 6
VISION_PROMPT = """下面按顺序是一条短视频里 {n} 个镜头各截的一帧画面，以及每个镜头本来要拍的内容。请逐帧对照检查。

{beats}

只输出一个 JSON 对象，不要解释：
{{"frames": [{{"no": 镜头序号, "people": 画面里清楚可见的人数, "has_text": 画面里有没有文字字幕水印（true 或 false）,
  "match": "相符、部分相符 或 不符", "problem": "不相符的地方，一句话；相符就留空"}}]}}"""


def extract_frames(path, times: List[float], width: int = VISION_FRAME_WIDTH) -> List[bytes]:
    """在给定时间点各截一帧（JPEG）。截不到的那一帧跳过。"""
    out = []
    for t in times:
        r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-v", "error", "-ss", f"{max(t, 0):.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            out.append(r.stdout)
    return out


def vision_messages(beats: list, frames: List[bytes]) -> list:
    """看图模型的消息：一段文字 + 每个镜头一张图（OpenAI 兼容的多段 content）。"""
    import base64
    lines = []
    for i, b in enumerate(beats[:len(frames)], start=1):
        desc = "，".join(str(b.get(k) or "") for k in ("shot_size", "composition", "action") if b.get(k))
        lines.append(f"镜头 {i}：{desc}")
    content = [{"type": "text", "text": VISION_PROMPT.format(n=len(frames), beats="\n".join(lines))}]
    for f in frames:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(f).decode("ascii")}})
    return [{"role": "user", "content": content}]


def vision_notes(raw, n: int) -> List[str]:
    """看图模型的回答 → 给人看的结论。结构不对返回空列表。"""
    notes = []
    frames = raw.get("frames") if isinstance(raw, dict) else None
    for f in frames if isinstance(frames, list) else []:
        if not isinstance(f, dict):
            continue
        try:
            no = int(f.get("no"))
        except (TypeError, ValueError):
            continue
        if not 1 <= no <= n:
            continue
        if f.get("has_text") is True:
            notes.append(f"成片看图：第 {no} 个小镜头画面里出现了文字或字幕")
        if str(f.get("match") or "") in ("不符", "部分相符") and str(f.get("problem") or "").strip():
            notes.append(f"成片看图：第 {no} 个小镜头与描述{f['match']}——{str(f['problem']).strip()[:50]}")
    return notes


async def review_content(llm, shot: dict, static_dir) -> Optional[dict]:
    """看图检查一条成片。返回 {"notes": [...], "frames": 帧数}；没有成片或小镜头返回 None；出错返回带 error 的结果。"""
    rel = shot.get("video_path")
    beats = [b for b in (shot.get("beats") or []) if isinstance(b, dict) and b.get("start") is not None][:VISION_MAX_FRAMES]
    if not rel or not beats:
        return None
    f = Path(rel) if Path(rel).is_absolute() else Path(static_dir) / rel
    if not f.exists():
        return None
    try:
        frames = extract_frames(f, [(float(b["start"]) + float(b["end"])) / 2 for b in beats])
        if not frames:
            return {"error": "截帧失败", "notes": []}
        raw = await llm.chat_json(vision_messages(beats, frames), max_tokens=2000)
        return {"notes": vision_notes(raw, len(frames)), "frames": len(frames)}
    except Exception as e:
        logger.warning("成片看图检查失败 %s: %s", f, e)
        return {"error": str(e)[:200], "notes": []}
