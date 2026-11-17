"""授权服务地址与续租相关常量（L-41）。

- DEFAULT_SERVER_URL 是占位地址，**发版前必须替换为正式授权服务地址**（与 license_keys.py 的公钥一起检查）。
- 环境变量 DONGAI_LICENSE_SERVER 只在 DONGAI_LICENSE_DEV=1 且非桌面模式时才允许覆盖，规则与公钥一致；
  桌面模式一律忽略，避免用户把授权请求指向自建的假服务器。
- 宽限期、续租间隔等不允许由环境变量修改。
"""
from __future__ import annotations

import logging
import os

from config import paths
from core import license_keys, version

logger = logging.getLogger(__name__)

# 【发版前替换】正式授权服务地址（必须是 https）。
DEFAULT_SERVER_URL = "https://license.example.com"

SERVER_ENV = "DONGAI_LICENSE_SERVER"
DEV_ENV = "DONGAI_LICENSE_DEV"
RENEW_ENV = "DONGAI_LICENSE_RENEW"

API_PREFIX = "/license/v1"
HTTP_TIMEOUT_SECONDS = 10
# 版本、平台、渠道的单一来源见 core/version.py（仓库根 VERSION）；测试构建的 +testbuild 也在那里加。
APP_VERSION = version.base_version() + (version.TEST_SUFFIX if license_keys.TEST_BUILD else "")  # 同 version.get_version()
APP_PLATFORM = version.get_platform()
APP_CHANNEL = version.get_channel()


def get_server_url() -> str:
    """授权服务地址（不带结尾斜杠）。测试构建固定用构建时写入的本机地址；其余见模块头说明。"""
    if license_keys.TEST_BUILD and license_keys.TEST_LICENSE_SERVER:
        return license_keys.TEST_LICENSE_SERVER.rstrip("/")
    if not paths.is_desktop() and os.environ.get(DEV_ENV, "").strip() == "1":
        custom = os.environ.get(SERVER_ENV, "").strip()
        if custom:
            if custom.lower().startswith(("http://", "https://")):
                return custom.rstrip("/")
            logger.warning("DONGAI_LICENSE_SERVER 格式不正确，已忽略")
    return DEFAULT_SERVER_URL.rstrip("/")


def update_url() -> str:
    """更新检查接口地址：授权服务地址 + /license/v1/update（与授权地址同一套来源规则，桌面模式不认环境变量）。"""
    return get_server_url() + API_PREFIX + "/update"


def renewer_enabled() -> bool:
    """续租线程是否启用：桌面模式一律启用；非桌面模式仅 DONGAI_LICENSE_RENEW=1 时启用。"""
    if paths.is_desktop():
        return True
    return os.environ.get(RENEW_ENV, "").strip() == "1"
