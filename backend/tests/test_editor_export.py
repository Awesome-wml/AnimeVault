"""剪映/CapCut 导出：每段时长与宽高按实际成片；打开剪辑软件跨平台、失败不抛。"""
from core.editor_export import clip_timing, open_editor_app


def test_clip_timing_uses_probe():
    assert clip_timing("a.mp4", {"duration": 15}, 5_000_000, probe=lambda p: (12.5, 720, 1280)) == (12_500_000, 720, 1280)


def test_clip_timing_falls_back_to_shot_then_template():
    def boom(p):
        raise RuntimeError("no ffmpeg")
    assert clip_timing("a.mp4", {"duration": 9}, 5_000_000, probe=boom) == (9_000_000, 1280, 720)
    assert clip_timing("a.mp4", {}, 5_000_000, probe=lambda p: (None, None, None)) == (5_000_000, 1280, 720)


def test_open_editor_app_platforms():
    calls = []
    assert open_editor_app("jianying", "darwin", {}, popen=calls.append) is True
    assert calls[-1] == ["open", "-a", "VideoFusion-macOS"]
    env = {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    assert open_editor_app("capcut", "win32", env, popen=calls.append, exists=lambda p: True) is True
    assert calls[-1][0].endswith("CapCut.exe")
    assert open_editor_app("jianying", "win32", env, popen=calls.append, exists=lambda p: False) is False

    def raising(_):
        raise OSError("x")
    assert open_editor_app("jianying", "darwin", {}, popen=raising) is False
    assert open_editor_app("jianying", "linux", {}, popen=calls.append) is False


def test_collect_entries_per_clip_durations(monkeypatch):
    from core import draft_subtitle as ds
    monkeypatch.setattr(ds, "_recognize_one", lambda shot, path: [(0.0, 1.0, shot["t"])])
    got = ds.collect_entries([({"t": "a"}, "p1"), ({"t": "b"}, "p2")], [10.0, 5.0])
    assert [(e["text"], e["start"]) for e in got] == [("a", 0.0), ("b", 10.0)]
    got = ds.collect_entries([({"t": "a"}, "p1"), ({"t": "b"}, "p2")], 7.0)
    assert got[1]["start"] == 7.0
