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

logger = logging.getLogger(__name__)

# 【发版前替换】正式授权服务地址（必须是 https）。
DEFAULT_SERVER_URL = "https://license.example.com"

SERVER_ENV = "DONGAI_LICENSE_SERVER"
DEV_ENV = "DONGAI_LICENSE_DEV"
RENEW_ENV = "DONGAI_LICENSE_RENEW"

API_PREFIX = "/license/v1"
HTTP_TIMEOUT_SECONDS = 10
APP_VERSION = "1.0.0"  # 随续租上报给服务端，仅用于运营统计


def get_server_url() -> str:
    """授权服务地址（不带结尾斜杠）。"""
    if not paths.is_desktop() and os.environ.get(DEV_ENV, "").strip() == "1":
        custom = os.environ.get(SERVER_ENV, "").strip()
        if custom:
            if custom.lower().startswith(("http://", "https://")):
                return custom.rstrip("/")
            logger.warning("DONGAI_LICENSE_SERVER 格式不正确，已忽略")
    return DEFAULT_SERVER_URL.rstrip("/")


def renewer_enabled() -> bool:
    """续租线程是否启用：桌面模式一律启用；非桌面模式仅 DONGAI_LICENSE_RENEW=1 时启用。"""
    if paths.is_desktop():
        return True
    return os.environ.get(RENEW_ENV, "").strip() == "1"
