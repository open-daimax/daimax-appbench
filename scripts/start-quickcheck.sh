#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
CONFIG_PATH="${QUICKCHECK_CONFIG:-$PROJECT_ROOT/evalapp.yaml}"
PORT="${QUICKCHECK_PORT:-8766}"
OUTPUT_PATH="${QUICKCHECK_OUTPUT:-}"
WORKERS="${QUICKCHECK_WORKERS:-5}"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/evalapp" ]]; then
  echo '缺少项目 Python 环境，请先执行 uv sync --extra quickcheck。' >&2
  exit 1
fi
if ! "$PROJECT_ROOT/.venv/bin/python" -c "import playwright" >/dev/null 2>&1; then
  echo '缺少浏览器采集依赖，请执行 uv sync --extra quickcheck，并运行 .venv/bin/python -m playwright install chromium。' >&2
  exit 1
fi
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "缺少配置文件：$CONFIG_PATH。请参考 evalapp.yaml.example 创建本地配置。" >&2
  exit 1
fi
if [[ "${QUICKCHECK_BUILD_UI:-0}" == 1 ]]; then
  npm --prefix "$PROJECT_ROOT/report-ui" ci --registry=https://registry.npmjs.org
  npm --prefix "$PROJECT_ROOT/report-ui" run build:quickcheck
fi
printf 'QuickCheck: http://127.0.0.1:%s/\n' "$PORT"
printf '停止服务：Ctrl+C\n'
ARGS=(--host 127.0.0.1 --port "$PORT" --workers "$WORKERS")
if [[ -n "$OUTPUT_PATH" ]]; then ARGS+=(--output "$OUTPUT_PATH"); fi
if [[ -n "${QUICKCHECK_SHARE_HOST:-}" ]]; then ARGS+=(--share-host "$QUICKCHECK_SHARE_HOST" --share-port "${QUICKCHECK_SHARE_PORT:-$((PORT+1))}"); fi
exec "$PROJECT_ROOT/.venv/bin/evalapp" --config "$CONFIG_PATH" quickcheck-ui "${ARGS[@]}"
