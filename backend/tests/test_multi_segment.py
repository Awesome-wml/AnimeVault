"""多段续接（《多段续接视频脚本写法规范》）：接缝类型、单段硬检查、按场景算台词占比、续接链排队、导出剪接缝重叠。

不依赖 Mongo 的单元测试；批量生成接口用 mongomock-motor 跑（没装就跳过）。
"""
import asyncio

import pytest

import core.shot_timing as ST
from core.editor_export import seam_trims
from core.prev_frame import CUT_REASON, PREV_FRAME_OFFSET_SECONDS, plan_chains, waves
from core.video_models import get_video_model
from core import video_prompt as VP

FAST = get_video_model()


def _seg(scene, lines, joint=None, duration=15, beats=None, **kw):
    seg = {"scene": scene, "lines": lines, "duration": duration,
           "beats": beats if beats is not None else [
               {"start": 0, "end": duration, "action": "赵虎上前一步", "move": "固定", "line_refs": [1]}]}
    if joint is not None:
        seg["joint"] = joint
    seg.update(kw)
    return seg


def _line(speaker, text, kind="onscreen", start=None, end=None):
    ln = {"speaker": speaker, "text": text, "kind": kind}
    if start is not None:
        ln["start"], ln["end"] = start, end
    return ln


# ---------- 口径 ----------
def test_pacing_leaves_room_for_handoff():
    """15 秒段台词 8 到 10 秒；最后一句至少在段尾前 1 秒念完。"""
    from core.video_models import segment_params
    p = segment_params(FAST)
    assert (p["content_low"], p["content_high"]) == (8, 10)
    lines = [_line("赵虎", "一二三四五六七八九十" * 5)]   # 50 字 = 10 秒
    seg, _ = ST.normalize_segment({"lines": lines, "beats": []}, FAST)
    assert seg[0]["lines"][-1]["end"] <= seg[0]["duration"] - ST.SEGMENT_TAIL_SECONDS + 1e-6


# ---------- 接缝类型 ----------
def test_normalize_joint():
    assert ST.normalize_joint("切镜") == ST.normalize_joint("cut") == "cut"
    assert ST.normalize_joint("续接") == ST.normalize_joint("承接上一段") == "continue"
    assert ST.normalize_joint("") == ST.normalize_joint(None) == ST.normalize_joint("随便") == ""


def test_assign_joints_scene_start_is_cut():
    segs = [_seg("演武场，黄昏", [], joint="续接"), _seg("演武场，黄昏", []), _seg("演武场，黄昏", [], joint="切镜"),
            _seg("宿舍，深夜", [], joint="续接")]
    ST.assign_joints(segs)
    assert [s["joint"] for s in segs] == ["cut", "continue", "cut", "cut"]


def test_rebalance_does_not_merge_across_cut():
    a = _seg("演武场，暴雨", [_line("旁白", "雨很大。", "narration")])
    b = _seg("演武场，暴雨", [_line("旁白", "夜深了。", "narration")], joint="切镜")
    out, notes = ST.rebalance_segments([a, b], FAST)
    assert out == [a, b] and not notes
    out2, notes2 = ST.rebalance_segments([a, dict(b, joint="续接")], FAST)
    assert len(out2) == 1 and notes2


# ---------- 单段硬检查 ----------
def _codes(seg):
    return {c["code"] for c in ST.segment_checks(seg)}


def test_segment_checks_pass_for_spec_example():
    seg = _seg("演武场", [_line("赵虎", "把东西交出来，我不想动手。", start=3, end=5.2),
                          _line("厉铮", "师兄说笑了，我一个扫地的，能藏什么？", start=7, end=10)],
               beats=[{"start": 0, "end": 7, "action": "赵虎踩水上前一步", "move": "缓慢推近"},
                      {"start": 7, "end": 15, "action": "厉铮右手缩进袖口", "move": "固定"}])
    assert ST.segment_checks(seg) == []


def test_segment_checks_flag_crowded_segment():
    lines = [_line("赵虎", "一" * 21, start=0.5, end=4.7), _line("厉铮", "嗯", start=5, end=5.6),
             _line("王婶", "你们别吵了", start=6, end=7), _line("旁白", "雨更大了", "narration", start=7.3, end=8.1),
             _line("赵虎", "滚开", start=8.4, end=14.8)]
    seg = _seg("演武场", lines, beats=[{"start": 0, "end": 15, "action": "众人对峙", "move": "横移",
                                        "boundary": ""}])
    assert {"long_line", "many_lines", "many_speakers", "tail_speech", "unstable_tail"} <= _codes(seg)


def test_segment_checks_idle_gap_and_fx_tail():
    seg = _seg("演武场", [_line("赵虎", "站住", start=0.5, end=1.3)],
               beats=[{"start": 0, "end": 5, "action": "", "move": "固定"},
                      {"start": 5, "end": 15, "action": "金光一闪", "move": "固定", "boundary": "金光只在掌心"}])
    codes = _codes(seg)
    assert "idle_gap" in codes and "unstable_tail" in codes


def test_legacy_shot_has_no_checks():
    assert ST.segment_checks({"text": "旧数据", "duration": 5}) == []


# ---------- 按场景算台词占比 ----------
def test_scene_summaries_weight_by_segment_type():
    """规范示例：两段对手戏 + 一段动作段，整场 45% 也算正常（目标区间按段型加权）。"""
    d1 = _seg("演武场，黄昏", [_line("赵虎", "一" * 39)])          # 7.8 秒
    d2 = _seg("演武场，黄昏", [_line("赵虎", "一" * 46)], joint="continue")   # 9.2 秒
    act = _seg("演武场，黄昏", [_line("旁白", "一" * 17, "narration")], joint="cut")   # 3.4 秒 → 动作段
    other = _seg("宿舍，深夜", [_line("旁白", "一" * 50, "narration")])
    out = ST.scene_summaries([d1, d2, act, other])
    s = out[0]
    assert s["segments"] == 3 and s["first"] and not out[1]["first"] and out[2]["key"] == s["key"]
    assert s["ratio"] == pytest.approx(20.4 / 45, abs=0.01) and s["status"] == "ok"
    assert s["low"] == pytest.approx((0.55 * 30 + 0.10 * 15) / 45, abs=0.01)
    assert out[3]["index"] == 2 and out[3]["segments"] == 1
    assert [x["chain"] for x in out[:3]] == [1, 2, 1]


def test_scene_summaries_flag_overfull_scene():
    full = [_seg("演武场", [_line("赵虎", "一" * 65)]) for _ in range(2)]   # 13 秒 / 15 秒 = 87%
    assert ST.scene_summaries(full)[0]["status"] == "high"


def test_long_continue_chain_warns():
    segs = [_seg("演武场", [_line("赵虎", "一" * 40)], joint="continue") for _ in range(6)]
    sums = ST.scene_summaries(segs)
    assert [s["chain"] for s in sums] == [1, 2, 3, 4, 5, 6]
    assert ST.chain_checks(sums[3]) == [] and ST.chain_checks(sums[4])[0]["code"] == "long_chain"


# ---------- 续接链排队 ----------
def test_plan_chains_and_waves():
    shots = [{"shot_no": 1, "joint": "cut"}, {"shot_no": 2}, {"shot_no": 3, "joint": "cut"},
             {"shot_no": 4, "joint": "continue"}, {"shot_no": 6}]
    plan = plan_chains(shots)
    assert [[s["shot_no"] for s in c] for c in plan["chains"]] == [[1, 2], [3, 4], [6]]
    assert plan["pred"] == {2: 1, 4: 3}
    assert [[s["shot_no"] for s in w] for w in waves(plan["chains"])] == [[1, 3, 6], [2, 4]]
    # 不用尾帧：每段各自一条链，一波全并行
    assert len(waves(plan_chains(shots, use_prev_frame=False)["chains"])) == 1


# ---------- 导出剪接缝重叠 ----------
def test_seam_trims_only_before_continued_segment():
    us = 15_000_000
    shots = [{"prev_frame_attached": False}, {"prev_frame_attached": True}, {}, {"prev_frame_attached": True}]
    off = int(PREV_FRAME_OFFSET_SECONDS * 1_000_000)
    assert seam_trims(shots, [us, us, us, us]) == [off, 0, off, 0]
    assert seam_trims([{}, {"prev_frame_attached": True}], [off * 2, us]) == [0, 0]   # 太短不剪


# ---------- 精简版提示词 ----------
def test_compact_prompt_keeps_shot_info():
    seg = {"shot_no": 1, "duration": 15, "scene": "演武场，黄昏", "characters": ["赵虎"],
           "lines": [_line("赵虎", "把东西交出来。", start=0.5, end=2.9)],
           "beats": [{"start": 0, "end": 15, "shot_size": "近景", "camera": "正对人物", "composition": "头肩",
                      "move": "固定", "action": "赵虎五指收拢攥紧", "expression": "眉毛一挑", "line_refs": [1]}],
           "video_prompt": "[0-15秒]近景，正对人物，固定；赵虎五指收拢攥紧；赵虎说：（台词①）"}
    full = VP.assemble_video_prompt_ex(seg, [], compact=False)[0]
    short = VP.assemble_video_prompt_ex(seg, [], compact=True)[0]
    assert len(short) < len(full)
    for kept in ("赵虎五指收拢攥紧", "把东西交出来", "【硬性参数】", "【画面】"):
        assert kept in short
    assert VP.SPEECH_RULES not in short and VP.SPEECH_RULES_COMPACT in short
    assert VP.assemble_video_prompt_ex(seg, [])[0] == full   # 默认关


# ---------- 批量生成：续接链 ----------
def _setup_batch(monkeypatch, tmp_path):
    mm = pytest.importorskip("mongomock_motor")
    from bson import ObjectId
    import api.video as V
    from config.settings import settings

    monkeypatch.setenv("DONGAI_FAKE_PROVIDERS", "1")
    monkeypatch.setattr(settings, "STATIC_DIR", str(tmp_path / "static"))
    db = mm.AsyncMongoMockClient()["test_multi_segment"]
    monkeypatch.setattr(V, "get_db", lambda: db)

    class Pool:
        def __init__(self):
            pass

        def get_total_available_quota(self):
            return 99

        def _alloc(self, n):
            return [{"account_id": "a1", "account_name": "测试号", "task_indices": list(range(n)), "cookies": []}]

        allocate_tasks = allocate_parallel = _alloc

        def increment_usage(self, *_):
            pass

        def set_cookies(self, *_):
            pass

        def save_generation_quota(self, *_):
            pass

    monkeypatch.setattr(V, "DoubaoAccountPool", Pool)
    pid = str(ObjectId())
    uid = ObjectId()
    loop = asyncio.new_event_loop()   # 其他测试可能关掉了默认事件循环
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.projects.insert_one({"_id": ObjectId(pid), "user_id": str(uid)}))
    return V, db, pid, {"_id": uid}, loop


@pytest.mark.parametrize("parallel", [False, True])
def test_batch_chains_tail_frames(monkeypatch, tmp_path, parallel):
    V, db, pid, user, loop = _setup_batch(monkeypatch, tmp_path)
    lines = [_line("赵虎", "把东西交出来。", start=0.5, end=2.9)]
    docs = [dict(_seg("演武场", lines, joint=j), project_id=pid, user_id=str(user["_id"]), shot_no=i + 1,
                 video_set_id=None, video_path=None)
            for i, j in enumerate(["cut", "continue", "cut"])]
    loop.run_until_complete(db.shots.insert_many(docs))
    resp = loop.run_until_complete(V.generate_batch_videos(project_id=pid, parallel=parallel, user=user))
    assert resp.data["success_count"] == 3
    shots = loop.run_until_complete(db.shots.find({"project_id": pid}).sort("shot_no", 1).to_list(None))
    assert all(s["video_path"] for s in shots)
    # 第 2 段是续接段：第 1 段在同一批里先出片，第 2 段组装时截得到它的尾帧；切镜段不带
    assert [s.get("prev_frame_attached") for s in shots] == [False, True, False]


def test_batch_skips_continuation_after_failure(monkeypatch, tmp_path):
    V, db, pid, user, loop = _setup_batch(monkeypatch, tmp_path)
    from core.doubao_automation import DoubaoVideoGenerator

    real = DoubaoVideoGenerator._fake_generate

    def flaky(self, tasks, on_video_ready=None, prepare_task=None):
        # 第 1 段失败：不出片
        def prep(t):
            t = prepare_task(t) if prepare_task else t
            return {**t, "skip": "模拟失败"} if t.get("shot_no") == 1 else t
        return real(self, tasks, on_video_ready=on_video_ready, prepare_task=prep)

    monkeypatch.setattr(DoubaoVideoGenerator, "_fake_generate", flaky)
    docs = [dict(_seg("演武场", [_line("赵虎", "交出来。")], joint=j), project_id=pid, user_id=str(user["_id"]),
                 shot_no=i + 1, video_set_id=None, video_path=None)
            for i, j in enumerate(["cut", "continue", "cut"])]
    loop.run_until_complete(db.shots.insert_many(docs))
    resp = loop.run_until_complete(V.generate_batch_videos(project_id=pid, parallel=False, user=user))
    reasons = resp.data["results"][0]["failed_reasons"]
    assert resp.data["success_count"] == 1 and set(resp.data["results"][0]["failed_shots"]) == {1, 2}
    assert "续接段" in reasons["2"]["msg"]


def test_cut_segment_skips_prev_frame(monkeypatch, tmp_path):
    V, db, pid, user, loop = _setup_batch(monkeypatch, tmp_path)
    from utils.file_util import FileUtil
    shot = dict(_seg("演武场", [_line("赵虎", "交出来。")], joint="cut"), project_id=pid, shot_no=2, _id="x")
    task = loop.run_until_complete(
        V.build_video_task(db, shot, None, [], [], [], FileUtil.get_static_dir()))
    assert task["prev_frame"] == {"attached": False, "image": None, "reason": CUT_REASON}
