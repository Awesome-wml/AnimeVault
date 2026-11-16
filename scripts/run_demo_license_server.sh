#!/usr/bin/env bash
# 启动演示授权服务（内存仓库）：用固定测试私钥签发，配合 `build_backend.py --test-public-key` 构建的测试包。
# 内存仓库：进程重启后所有已签发的授权、管理员改动都会丢失（管理员由 e2e_super/e2e_ops/e2e_readonly 重建）。
# 用法：E2E_ADMIN_PASSWORD='至少12位' scripts/run_demo_license_server.sh [端口，默认 18100]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export E2E_SIGNING_KEY_FILE="${E2E_SIGNING_KEY_FILE:-$HOME/.local/dongai-test-license/signing.key}"
export E2E_LICENSE_PORT="${1:-${E2E_LICENSE_PORT:-18100}}"
: "${E2E_ADMIN_PASSWORD:?请设置 E2E_ADMIN_PASSWORD（至少 12 位）}"
PY="${DONGAI_PYTHON:-python3}"
exec "$PY" "$ROOT/license-admin/e2e/start_server.py"
