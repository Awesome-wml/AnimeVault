"""集中管理桌面模式下的数据目录与路径。

- 环境变量 DONGAI_DESKTOP=1 表示桌面模式；
- DONGAI_DATA_DIR 指定应用数据目录，未指定时按平台取默认值：
  macOS ~/Library/Application Support/DongAI，Windows %APPDATA%\\DongAI，Linux ~/.local/share/DongAI。
非桌面模式下所有路径保持原行为（相对仓库）。本模块不依赖 settings，避免循环导入。
"""
import os
import secrets
import sys
from pathlib import Path

APP_NAME = "DongAI"
_TRUE = ("1", "true", "yes", "on")

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


_FORCED_DESKTOP = False


def force_desktop() -> None:
    """桌面版可执行文件（desktop_entry）启动时调用：之后 is_desktop() 恒为 True，不再看环境变量。

    否则用户在命令行设 DONGAI_DESKTOP=0 直接运行打包后的后端，就能关掉授权拦截、
    重新打开账号注册，并解锁 DONGAI_LICENSE_DEV 的公钥/授权服务地址覆盖。
    """
    global _FORCED_DESKTOP
    _FORCED_DESKTOP = True
    os.environ["DONGAI_DESKTOP"] = "1"


def is_desktop() -> bool:
    if _FORCED_DESKTOP:
        return True
    return os.environ.get("DONGAI_DESKTOP", "").strip().lower() in _TRUE


def data_dir() -> Path:
    """应用数据目录（只读推导，不创建）。"""
    custom = os.environ.get("DONGAI_DATA_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def static_dir_default() -> Path:
    return _sub("static")


def logs_dir() -> Path:
    return _sub("logs")


def log_file() -> Path:
    """后端日志文件：桌面模式 <data>/logs/backend.log，否则 backend/backend.log。"""
    return logs_dir() / "backend.log" if is_desktop() else BACKEND_DIR / "backend.log"


def project_root() -> Path:
    """豆包 profile、output_videos 等相对路径的基准目录：桌面模式为数据目录，否则为仓库根。"""
    if is_desktop():
        data_dir().mkdir(parents=True, exist_ok=True)
        return data_dir()
    return REPO_ROOT


def doubao_accounts_json() -> Path:
    """旧版 doubao_accounts.json（仅用于首次导入）。"""
    return (data_dir() / "doubao_accounts.json") if is_desktop() else REPO_ROOT / "doubao_accounts.json"


def jianying_template_dir() -> Path:
    return (data_dir() / "jianying_template") if is_desktop() else BACKEND_DIR / ".jianying_template"


def debug_dump_dir() -> Path:
    """调试落盘目录（如 LLM 非法 JSON 原文）。"""
    return logs_dir() if is_desktop() else REPO_ROOT


def jwt_secret_file() -> Path:
    return data_dir() / "secrets" / "jwt.secret"


def license_file() -> Path:
    """已激活的授权码文件（不创建目录）：<data>/license/license.json。"""
    return data_dir() / "license" / "license.json"


def load_or_create_jwt_secret() -> str:
    """读取持久化的 JWT 密钥，不存在则随机生成并以 600 权限写入。"""
    f = jwt_secret_file()
    if f.exists():
        val = f.read_text(encoding="utf-8").strip()
        if val:
            return val
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(f.parent, 0o700)
    except OSError:
        pass
    val = secrets.token_hex(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(val)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return val
