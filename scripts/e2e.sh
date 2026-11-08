#!/usr/bin/env bash
# 端到端测试一条命令：起后端 + 前端 → 跑 pytest 接口测试 → 跑 Playwright 浏览器测试 → 停服务、删测试库。
#
#   scripts/e2e.sh                # 替身模式（默认）：外部服务全部替身，完整主流程
#   E2E_REAL=1 scripts/e2e.sh     # 真实模型冒烟：真智谱跑 小说 → 提取 → 分镜（只跑这一条）
#
# 必需（二选一）：
#   MONGODB_URL           或  E2E_MONGO_URL_FILE（文件里放连接串）
# 可选：
#   E2E_JWT_SECRET_FILE   JWT 密钥文件（不给则每次随机生成）
#   E2E_ZHIPU_KEY_FILE    E2E_REAL=1 时必需：智谱 API Key 文件（只在运行时读，不落盘、不打印）
#   E2E_PYTHON            后端 Python（默认 backend/.venv/bin/python，再退回 python3）
#   E2E_DB_NAME           测试库名（默认 dongai_e2e，必须含 e2e 或 test）
#   E2E_BACKEND_PORT      默认 8001        E2E_FRONTEND_PORT  默认 8081
#   E2E_REPORT_DIR        报告目录（默认 <仓库>/e2e-report）
#   E2E_KEEP_DB=1         跑完不删测试库（排查用）
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
REAL="${E2E_REAL:-0}"
DB_NAME="${E2E_DB_NAME:-dongai_e2e}"
BPORT="${E2E_BACKEND_PORT:-8001}"
FPORT="${E2E_FRONTEND_PORT:-8081}"
REPORT_DIR="${E2E_REPORT_DIR:-$ROOT/e2e-report}"
if [[ "$REAL" == "1" ]]; then REPORT_DIR="$REPORT_DIR/real"; fi

log() { printf '\033[1;34m[e2e]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[e2e] %s\033[0m\n' "$*" >&2; exit 2; }

# ---------- 准备 ----------
case "$DB_NAME" in dongai) die "拒绝使用主库 dongai";; *e2e*|*test*) ;; *) die "测试库名必须包含 e2e 或 test: $DB_NAME";; esac

if [[ -z "${MONGODB_URL:-}" ]]; then
  [[ -n "${E2E_MONGO_URL_FILE:-}" && -f "$E2E_MONGO_URL_FILE" ]] || die "请设置 MONGODB_URL 或 E2E_MONGO_URL_FILE"
  MONGODB_URL="$(tr -d '[:space:]' < "$E2E_MONGO_URL_FILE")"
fi
if [[ -n "${E2E_JWT_SECRET_FILE:-}" && -f "$E2E_JWT_SECRET_FILE" ]]; then
  JWT_SECRET="$(tr -d '[:space:]' < "$E2E_JWT_SECRET_FILE")"
else
  JWT_SECRET="$(openssl rand -hex 32)"
fi
if [[ "$REAL" == "1" ]]; then
  [[ -n "${E2E_ZHIPU_KEY_FILE:-}" && -f "$E2E_ZHIPU_KEY_FILE" ]] || die "E2E_REAL=1 需要 E2E_ZHIPU_KEY_FILE"
fi

PY="${E2E_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$BACKEND/.venv/bin/python" ]]; then PY="$BACKEND/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi
"$PY" -c "import uvicorn, pytest, httpx, pymongo" 2>/dev/null || die "$PY 缺少依赖：pip install -r backend/requirements.txt -r backend/requirements-dev.txt"
[[ -x "$FRONTEND/node_modules/.bin/playwright" ]] || die "缺少 @playwright/test：cd frontend && npm install"

for port in "$BPORT" "$FPORT"; do
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then die "端口 $port 已被占用"; fi
done

# 本机前后端互访不走代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY MONGO_URL
export NO_PROXY="127.0.0.1,localhost"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/dongai-e2e.XXXXXX")"
mkdir -p "$WORK/static" "$WORK/jianying"
rm -rf "$REPORT_DIR"; mkdir -p "$REPORT_DIR"
BACKEND_LOG="$REPORT_DIR/backend.log"
FRONTEND_LOG="$REPORT_DIR/frontend.log"

export MONGODB_URL MONGODB_DB_NAME="$DB_NAME" JWT_SECRET
export STATIC_DIR="$WORK/static" JIANYING_DRAFT_DIR="$WORK/jianying"
export JIANYING_TEMPLATE_DIR="$BACKEND/tests/fixtures/jianying_template"
export REDIS_URL="redis://127.0.0.1:6/0"   # 不连 Redis（可选组件）
if [[ "$REAL" == "1" ]]; then unset DONGAI_FAKE_PROVIDERS; else export DONGAI_FAKE_PROVIDERS=1; fi

BPID=""; FPID=""
cleanup() {
  local code=$?
  log "收尾：停止服务"
  [[ -n "$FPID" ]] && kill "$FPID" 2>/dev/null
  [[ -n "$BPID" ]] && kill "$BPID" 2>/dev/null
  # vue-cli 会派生子进程，按端口兜底
  for port in "$FPORT" "$BPORT"; do
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null
  done
  if [[ "${E2E_KEEP_DB:-0}" != "1" ]]; then
    (cd "$BACKEND" && "$PY" tests/e2e_db.py drop && "$PY" tests/e2e_db.py check "$WORK/main_before.json") | sed 's/^/[e2e] /'
  fi
  rm -rf "$WORK"
  exit "$code"
}
trap cleanup EXIT INT TERM

wait_http() {  # url 秒数 名称
  local url="$1" secs="$2" name="$3"
  for _ in $(seq 1 "$secs"); do
    if curl -sf -o /dev/null "$url"; then log "$name 已就绪：$url"; return 0; fi
    sleep 1
  done
  die "$name 在 ${secs}s 内没有就绪，日志：$4"
}

# ---------- 启动 ----------
log "重置测试库 $DB_NAME"
(cd "$BACKEND" && "$PY" tests/e2e_db.py snapshot) > "$WORK/main_before.json" || die "无法连接 Mongo"
(cd "$BACKEND" && "$PY" tests/e2e_db.py reset) | sed 's/^/[e2e] /' || die "测试库重置失败"

log "启动后端 :${BPORT}（$([[ "$REAL" == "1" ]] && echo 真实模型 || echo 替身模式)）"
(cd "$BACKEND" && exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$BPORT") > "$BACKEND_LOG" 2>&1 &
BPID=$!

log "启动前端 dev server :${FPORT}（代理 → :${BPORT}）"
(cd "$FRONTEND" && DONGAI_API_TARGET="http://127.0.0.1:$BPORT" BROWSER=none \
  exec node_modules/.bin/vue-cli-service serve --host 127.0.0.1 --port "$FPORT") > "$FRONTEND_LOG" 2>&1 &
FPID=$!

wait_http "http://127.0.0.1:$BPORT/health" 60 "后端" "$BACKEND_LOG"
wait_http "http://127.0.0.1:$FPORT/" 180 "前端" "$FRONTEND_LOG"

# ---------- 测试 ----------
STATUS=0
export DONGAI_API_BASE="http://127.0.0.1:$BPORT"
if [[ "$REAL" != "1" ]]; then
  log "pytest 接口测试"
  (cd "$BACKEND" && "$PY" -m pytest tests -q --junitxml="$REPORT_DIR/pytest-junit.xml") 2>&1 | tee "$REPORT_DIR/pytest.txt"
  [[ ${PIPESTATUS[0]} -eq 0 ]] || STATUS=1
fi

(cd "$BACKEND" && "$PY" tests/e2e_db.py accounts) | sed 's/^/[e2e] /'
log "Playwright 浏览器测试"
(cd "$FRONTEND" && E2E_BASE_URL="http://127.0.0.1:$FPORT" E2E_REPORT_DIR="$REPORT_DIR" E2E_REAL="$REAL" \
  E2E_ZHIPU_KEY_FILE="${E2E_ZHIPU_KEY_FILE:-}" \
  node_modules/.bin/playwright test -c e2e/playwright.config.js) 2>&1 | tee "$REPORT_DIR/playwright.txt"
[[ ${PIPESTATUS[0]} -eq 0 ]] || STATUS=1

echo
log "HTML 报告：$REPORT_DIR/html/index.html"
log "每步截图：$REPORT_DIR/screenshots/"
[[ "$REAL" != "1" ]] && log "pytest 结果：$REPORT_DIR/pytest.txt（JUnit：$REPORT_DIR/pytest-junit.xml）"
log "服务日志：$BACKEND_LOG  $FRONTEND_LOG"
if [[ $STATUS -eq 0 ]]; then log "全部通过"; else printf '\033[1;31m[e2e] 有用例失败\033[0m\n'; fi
exit $STATUS
