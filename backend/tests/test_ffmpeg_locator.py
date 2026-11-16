"""ffmpeg 解析器：env > 包内 bin > PATH；缺失报中文错误；Windows 后缀。"""
import os
import stat
import sys

import pytest

from core import ffmpeg_locator as fl


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    for k in (*fl.ENV_BIN.values(), fl.APP_DIR_ENV, fl.RESOURCES_DIR_ENV):
        monkeypatch.delenv(k, raising=False)
    # 隔离 sys.argv[0]/sys.executable 旁的 bin 与 PATH
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "nowhere" / "app")])
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nowhere" / "py"))
    monkeypatch.setattr(fl.shutil, "which", lambda n: None)


def _fake(path, body="#!/bin/sh\necho 'ffmpeg version 9.9-test'\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_env_wins_over_bundle_and_path(monkeypatch, tmp_path):
    env_bin = _fake(tmp_path / "e" / "ffmpeg")
    _fake(tmp_path / "app" / "bin" / "ffmpeg")
    monkeypatch.setenv(fl.APP_DIR_ENV, str(tmp_path / "app"))
    monkeypatch.setattr(fl.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setenv("DONGAI_FFMPEG_BIN", str(env_bin))
    assert fl.locate("ffmpeg") == env_bin


def test_env_pointing_to_missing_file_is_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DONGAI_FFMPEG_BIN", str(tmp_path / "nope"))
    monkeypatch.setattr(fl.shutil, "which", lambda n: "/usr/bin/" + n)
    with pytest.raises(fl.FFmpegNotFoundError) as ei:
        fl.locate("ffmpeg")
    assert "未找到视频处理组件，请重新安装软件" in str(ei.value)


@pytest.mark.skipif(sys.platform == "win32", reason="posix 后缀")
def test_bundle_before_path(monkeypatch, tmp_path):
    b = _fake(tmp_path / "app" / "bin" / "ffprobe")
    monkeypatch.setenv(fl.APP_DIR_ENV, str(tmp_path / "app"))
    monkeypatch.setattr(fl.shutil, "which", lambda n: "/usr/bin/" + n)
    assert fl.locate("ffprobe") == b


def test_resources_dir_and_argv_dir(monkeypatch, tmp_path):
    suffix = ".exe" if sys.platform == "win32" else ""
    r = _fake(tmp_path / "res" / "bin" / f"ffmpeg{suffix}")
    monkeypatch.setenv(fl.RESOURCES_DIR_ENV, str(tmp_path / "res"))
    assert fl.locate("ffmpeg") == r
    monkeypatch.delenv(fl.RESOURCES_DIR_ENV)
    a = _fake(tmp_path / "exe" / "bin" / f"ffmpeg{suffix}")
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "exe" / "dongai-backend")])
    assert fl.locate("ffmpeg") == a


def test_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr(fl.shutil, "which", lambda n: str(tmp_path / n))
    assert str(fl.locate("ffmpeg")) == str(tmp_path / "ffmpeg")


def test_missing_raises_chinese_message():
    with pytest.raises(fl.FFmpegNotFoundError) as ei:
        fl.locate("ffprobe")
    assert str(ei.value).startswith("未找到视频处理组件，请重新安装软件")
    assert ei.value.tool == "ffprobe"


def test_windows_suffix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert fl.exe_name("ffmpeg") == "ffmpeg.exe"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert fl.exe_name("ffprobe") == "ffprobe"


def test_windows_bundle_lookup(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    p = tmp_path / "app" / "bin" / "ffmpeg.exe"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    monkeypatch.setenv(fl.APP_DIR_ENV, str(tmp_path / "app"))
    assert fl.locate("ffmpeg") == p


def test_unknown_tool():
    with pytest.raises(ValueError):
        fl.locate("rm")


@pytest.mark.skipif(sys.platform == "win32", reason="用 shell 脚本冒充")
def test_check_ok_and_missing(monkeypatch, tmp_path):
    f = _fake(tmp_path / "a" / "ffmpeg")
    p = _fake(tmp_path / "a" / "ffprobe", "#!/bin/sh\necho 'ffprobe version 9.9-test'\n")
    monkeypatch.setenv("DONGAI_FFMPEG_BIN", str(f))
    monkeypatch.setenv("DONGAI_FFPROBE_BIN", str(p))
    r = fl.check()
    assert r["ok"] and r["ffmpeg"]["source"] == "env" and "9.9-test" in r["ffmpeg"]["version"]
    monkeypatch.delenv("DONGAI_FFPROBE_BIN")
    r = fl.check()
    assert not r["ok"] and "未找到视频处理组件" in r["ffprobe"]["error"]
