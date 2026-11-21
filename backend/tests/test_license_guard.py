

def test_force_desktop_ignores_env(monkeypatch):
    """打包后的后端（desktop_entry）强制桌面模式：DONGAI_DESKTOP=0 不能关掉授权拦截。"""
    from config import paths
    monkeypatch.setattr(paths, "_FORCED_DESKTOP", False)
    monkeypatch.setenv("DONGAI_DESKTOP", "0")
    assert paths.is_desktop() is False
    paths.force_desktop()
    try:
        monkeypatch.setenv("DONGAI_DESKTOP", "0")
        assert paths.is_desktop() is True
    finally:
        monkeypatch.setattr(paths, "_FORCED_DESKTOP", False)


def test_desktop_entry_does_not_use_setdefault():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "desktop_entry.py").read_text(encoding="utf-8")
    assert 'setdefault("DONGAI_DESKTOP"' not in src and "paths.force_desktop()" in src
