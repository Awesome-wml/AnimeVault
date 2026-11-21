"""static 目录外的路径（绝对路径、../）不能被读到或删掉。"""
import pytest

from utils.file_util import FileUtil, UnsafePathError


@pytest.fixture
def static(tmp_path, monkeypatch):
    # 其他测试会 reload config.settings，直接换掉 file_util 模块里引用的 settings 对象
    from types import SimpleNamespace
    import utils.file_util as fu
    monkeypatch.setattr(fu, "settings", SimpleNamespace(STATIC_DIR=str(tmp_path / "static")))
    return tmp_path


def test_safe_path_accepts_relative(static):
    p = FileUtil.safe_path("images/a.png")
    assert p == (static / "static" / "images" / "a.png").resolve()


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.txt", "images/../../outside.txt", "", "C:/x", "\\\\host\\share"])
def test_safe_path_rejects_escape(static, bad):
    with pytest.raises(UnsafePathError):
        FileUtil.safe_path(bad)


def test_delete_file_ignores_escape(static):
    victim = static / "outside.txt"
    victim.write_text("keep")
    FileUtil.delete_file("../outside.txt")
    FileUtil.delete_file(str(victim))
    assert victim.exists()
    inside = static / "static" / "images"
    inside.mkdir(parents=True)
    (inside / "a.png").write_bytes(b"x")
    FileUtil.delete_file("images/a.png")
    assert not (inside / "a.png").exists()
