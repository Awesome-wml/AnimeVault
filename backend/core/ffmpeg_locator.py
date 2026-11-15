"""解析 ffmpeg / ffprobe 的路径（桌面版随包带，开发环境用系统 PATH）。

查找顺序：
1. 环境变量 DONGAI_FFMPEG_BIN / DONGAI_FFPROBE_BIN（显式指定；指向不存在的文件视为配置错误，不再往下找）；
2. 包内 bin/ffmpeg[.exe]：依次看 DONGAI_APP_DIR（desktop_entry 设置为可执行包目录）、
   DONGAI_RESOURCES_DIR、sys.argv[0] 所在目录、sys.executable 所在目录 下的 bin/；
3. 系统 PATH。
都找不到抛 FFmpegNotFoundError（消息可直接展示给用户）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ENV_BIN = {"ffmpeg": "DONGAI_FFMPEG_BIN", "ffprobe": "DONGAI_FFPROBE_BIN"}
APP_DIR_ENV = "DONGAI_APP_DIR"
RESOURCES_DIR_ENV = "DONGAI_RESOURCES_DIR"
USER_MESSAGE = "未找到视频处理组件，请重新安装软件"


class FFmpegNotFoundError(RuntimeError):
    """找不到 ffmpeg / ffprobe。str(e) 是给用户看的中文提示。"""

    def __init__(self, tool: str, detail: str = ""):
        self.tool = tool
        self.detail = detail
        super().__init__(f"{USER_MESSAGE}（缺少 {tool}）" + (f"：{detail}" if detail else ""))


def exe_name(tool: str) -> str:
    return tool + (".exe" if sys.platform == "win32" else "")


def _bundle_dirs() -> List[Path]:
    dirs: List[Path] = []
    for env in (APP_DIR_ENV, RESOURCES_DIR_ENV):
        v = os.environ.get(env, "").strip()
        if v:
            dirs.append(Path(v).expanduser() / "bin")
    for base in (sys.argv[0] if sys.argv and sys.argv[0] else "", sys.executable):
        if base:
            dirs.append(Path(os.path.abspath(base)).parent / "bin")
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _is_file(p: Path) -> bool:
    return p.is_file()


def locate(tool: str) -> Path:
    """返回 tool（"ffmpeg" 或 "ffprobe"）的可执行文件路径，找不到抛 FFmpegNotFoundError。"""
    if tool not in ENV_BIN:
        raise ValueError(f"不支持的组件：{tool}")
    custom = os.environ.get(ENV_BIN[tool], "").strip()
    if custom:
        p = Path(custom).expanduser()
        if _is_file(p):
            return p
        raise FFmpegNotFoundError(tool, f"环境变量 {ENV_BIN[tool]} 指向的文件不存在：{p}")
    name = exe_name(tool)
    for d in _bundle_dirs():
        p = d / name
        if _is_file(p):
            return p
    found = shutil.which(tool)
    if found:
        return Path(found)
    raise FFmpegNotFoundError(tool)


def ffmpeg_path() -> str:
    return str(locate("ffmpeg"))


def ffprobe_path() -> str:
    return str(locate("ffprobe"))


def source_of(path: Path) -> str:
    """该路径来自哪一级：env / bundled / path。"""
    for tool, env in ENV_BIN.items():
        if os.environ.get(env, "").strip() and Path(os.environ[env]).expanduser() == path:
            return "env"
    if any(path.parent == d for d in _bundle_dirs()):
        return "bundled"
    return "path"


def _version(path: Path) -> Optional[str]:
    try:
        r = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    line = (r.stdout or "").splitlines()[0] if r.stdout else ""
    return line.strip() or None


def check() -> dict:
    """自检：ffmpeg 与 ffprobe 都能找到并能执行 -version。

    返回 {"ok": bool, "ffmpeg": {...}, "ffprobe": {...}}；每项含 path/source/version 或 error。
    """
    result: dict = {"ok": True}
    for tool in ("ffmpeg", "ffprobe"):
        item: dict = {}
        try:
            p = locate(tool)
            item.update(path=str(p), source=source_of(p))
            ver = _version(p)
            if ver:
                item["version"] = ver
            else:
                item["error"] = "无法执行 -version"
                result["ok"] = False
        except FFmpegNotFoundError as e:
            item["error"] = str(e)
            result["ok"] = False
        result[tool] = item
    return result
