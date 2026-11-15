#!/usr/bin/env bash
# 授权激活 e2e：起「最小后端（授权接口 + 全局拦截，不连数据库）」+ 前端 dev server，只跑 e2e/license.spec.js。
# 端口沿用 e2e.sh 约定 8001/8081，不碰 8000/8080 和任何数据库。
#   E2E_PYTHON  后端 Python（默认 backend/.venv/bin/python，再退回 python3）
#   E2E_BACKEND_PORT / E2E_FRONTEND_PORT  默认 8001 / 8081
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"; FRONTEND="$ROOT/frontend"
BPORT="${E2E_BACKEND_PORT:-8001}"; FPORT="${E2E_FRONTEND_PORT:-8081}"
REPORT_DIR="${E2E_REPORT_DIR:-$ROOT/e2e-report/license}"
PY="${E2E_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$BACKEND/.venv/bin/python" ]]; then PY="$BACKEND/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi
die() { printf '\033[1;31m[e2e-license] %s\033[0m\n' "$*" >&2; exit 2; }
"$PY" -c "import uvicorn, fastapi, cryptography" 2>/dev/null || die "$PY 缺少依赖（uvicorn/fastapi/cryptography）"
[[ -x "$FRONTEND/node_modules/.bin/playwright" ]] || die "缺少 @playwright/test：cd frontend && npm install"
for port in "$BPORT" "$FPORT"; do
  lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && die "端口 $port 已被占用"
done
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export NO_PROXY="127.0.0.1,localhost"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/dongai-e2e-license.XXXXXX")"
mkdir -p "$REPORT_DIR"
# 测试公钥：临时生成，私钥不落盘（本用例只验证无效码，不需要签发）
PUBKEYS="$(cd "$ROOT/license" && "$PY" -c "
import json
from dongai_license import crypto
print(json.dumps({'ke2e': crypto.generate_keypair()[1]}))")"

BPID=""; FPID=""
cleanup() {
  local code=$?
  [[ -n "$FPID" ]] && kill "$FPID" 2>/dev/null
  [[ -n "$BPID" ]] && kill "$BPID" 2>/dev/null
  for port in "$FPORT" "$BPORT"; do lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null; done
  rm -rf "$WORK"; exit "$code"
}
trap cleanup EXIT INT TERM

(cd "$BACKEND" && DONGAI_DATA_DIR="$WORK/data" DONGAI_LICENSE_ENFORCE=1 DONGAI_LICENSE_DEV=1 \
  DONGAI_LICENSE_PUBKEYS="$PUBKEYS" PYTHONPATH="$BACKEND:$BACKEND/tests" \
  exec "$PY" -m uvicorn license_e2e_app:app --host 127.0.0.1 --port "$BPORT") > "$REPORT_DIR/backend.log" 2>&1 &
BPID=$!
(cd "$FRONTEND" && DONGAI_API_TARGET="http://127.0.0.1:$BPORT" BROWSER=none \
  exec node_modules/.bin/vue-cli-service serve --host 127.0.0.1 --port "$FPORT") > "$REPORT_DIR/frontend.log" 2>&1 &
FPID=$!
wait_http() { for _ in $(seq 1 "$2"); do curl -sf -o /dev/null "$1" && return 0; sleep 1; done; die "$3 在 $2s 内没有就绪，日志在 $REPORT_DIR"; }
wait_http "http://127.0.0.1:$BPORT/health" 30 "后端"
wait_http "http://127.0.0.1:$FPORT/" 180 "前端"

cd "$FRONTEND" && E2E_BASE_URL="http://127.0.0.1:$FPORT" E2E_REPORT_DIR="$REPORT_DIR" E2E_LICENSE_ENFORCE=1 \
  node_modules/.bin/playwright test -c e2e/playwright.config.js license.spec.js
