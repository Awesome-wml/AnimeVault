"""客户端内置的授权公钥（kid -> Ed25519 公钥，base64url 无填充）。

【替换流程（正式发版前必须做）】
1. 在授权服务器所在的安全环境里运行 `license/scripts/gen_keys.py` 生成正式密钥对，
   私钥只留在服务器，绝不入库、不进安装包。
2. 把脚本打印的 kid 和公钥填进下面的 PUBLIC_KEYS，并删除「开发用」占位项。
3. 轮换时新旧 kid 并存一段时间（见 license/README.md 的 kid 轮换），确认旧授权全部过期或重签后再移除旧公钥。

注意：公钥只能写在这个文件里随安装包发布。桌面模式下环境变量 DONGAI_LICENSE_PUBKEYS 一律被忽略，
仅 DONGAI_LICENSE_DEV=1 且非桌面模式的开发环境才允许用它覆盖（见 core/license_client.py）。
"""

PUBLIC_KEYS: dict = {
    # 开发用占位公钥：对应私钥已销毁，任何授权码都无法由它验证通过。发版前必须替换。
    "1a8c8d43": "Up0OW4GwMoRAVlosLnuguLsUNNPXP2HBA0-R5MmTuTE",
}


# ---- 构建期测试公钥（仅 desktop/build_backend.py --test-public-key 的产物）------------------------------
# 构建脚本在编译前生成 core/_test_build.py（已 gitignore，编译后即删除），里面带测试公钥与本机授权服务地址。
# 正式构建里这个模块不存在，下面的 import 失败、保持上面的 PUBLIC_KEYS 不变。
# 有这个模块 = 测试构建：公钥被整体替换为测试公钥，启动日志、--build-info、版本号（+testbuild）都会带标记，
# desktop/check_release_build.py 用来确认正式包里没有它。
try:
    from core import _test_build as _tb  # type: ignore[attr-defined]
except ImportError:
    _tb = None

TEST_BUILD: bool = _tb is not None
TEST_BUILD_MARKER: str = getattr(_tb, "TEST_BUILD_MARKER", "")
TEST_LICENSE_SERVER: str = getattr(_tb, "LICENSE_SERVER", "")
if _tb is not None:
    PUBLIC_KEYS = dict(_tb.PUBLIC_KEYS)
