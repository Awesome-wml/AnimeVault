#!/usr/bin/env bash
# 一键构建桌面安装包（L-06）：前端 → 后端包（Nuitka）→ Electron（electron-builder）。
# 用法：desktop/build_all.sh [--dir] [--skip-frontend] [--skip-backend]
#   --dir            只出未打包的 .app（out/mac-arm64/DongAI.app），不出 dmg/zip，开发验证用
# 环境变量：
#   DONGAI_MONGOD_BIN  官方社区版 mongod 路径（见 docs/spike-mongod.md），构建后端必需
#   DONGAI_PYTHON      装了 Nuitka 的 Python，默认 ~/.local/dongai-venv/bin/python
#   签名/公证（L-09/L-10 使用，未设置则出未签名包）：CSC_LINK、CSC_KEY_PASSWORD、APPLE_ID、
#   APPLE_APP_SPECIFIC_PASSWORD、APPLE_TEAM_ID、WIN_CSC_LINK、WIN_CSC_KEY_PASSWORD
# 下载缓存放 ~/.local/dongai-build/，不动用户的 npm 缓存（~/.npm/_cacache 里有 root 属主文件）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${DONGAI_PYTHON:-$HOME/.local/dongai-venv/bin/python}"
CACHE="$HOME/.local/dongai-build"
export NPM_CONFIG_CACHE="$CACHE/npm-cache"
export ELECTRON_CACHE="$CACHE/electron-cache"
export ELECTRON_BUILDER_CACHE="$CACHE/electron-builder-cache"
mkdir -p "$NPM_CONFIG_CACHE" "$ELECTRON_CACHE" "$ELECTRON_BUILDER_CACHE"

DIR_ONLY=0; SKIP_FE=0; SKIP_BE=0
for a in "$@"; do
  case "$a" in
    --dir) DIR_ONLY=1 ;;
    --skip-frontend) SKIP_FE=1 ;;
    --skip-backend) SKIP_BE=1 ;;
    *) echo "未知参数 $a" >&2; exit 2 ;;
  esac
done

if [ "$SKIP_FE" = 0 ]; then
  echo "==> 构建前端"
  cd "$ROOT/frontend"
  if [ ! -e node_modules ]; then
    # worktree 里没有依赖时复用主仓库的（不要在这里 npm install）
    ln -s /Users/wangmaolin/IdeaProjects/dong-ai-manju/frontend/node_modules node_modules
  fi
  npm run build
fi

if [ "$SKIP_BE" = 0 ]; then
  echo "==> 构建后端包（Nuitka）"
  : "${DONGAI_MONGOD_BIN:?请设置 DONGAI_MONGOD_BIN，例如 ~/.local/dongai-spike/bin-arm64/mongodb-macos-aarch64-7.0.48/bin/mongod}"
  "$PY" "$ROOT/desktop/build_backend.py" --no-fixtures
fi

echo "==> 打包 Electron 外壳"
cd "$ROOT/desktop/shell"
npm install --no-audit --no-fund
node node_modules/electron/install.js >/dev/null 2>&1 || true

ARGS=()
if [ "$DIR_ONLY" = 1 ]; then ARGS+=(--dir); fi
case "$(uname -s)" in
  Darwin)
    ARGS+=(--mac dmg zip --arm64)   # x64 配置已写好但本机没有验证；要出 x64 另行加 --x64（需要 x64 后端包）
    # 有 Apple 公证凭据时自动打开公证（L-09）
    if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
      ARGS+=(-c.mac.notarize=true)
    fi
    ;;
  *) ARGS+=(--win --x64) ;;  # Windows 流程未实测
esac
# 没有 CSC_LINK 时 electron-builder 会跳过签名，产出未签名开发包
npx electron-builder "${ARGS[@]}"
echo "==> 完成，产物在 desktop/shell/out/"
