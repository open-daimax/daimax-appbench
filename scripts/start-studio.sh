#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PYTHON="${STUDIO_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
CONFIG_PATH="${STUDIO_CONFIG:-$PROJECT_ROOT/evalapp.yaml}"
if [[ ! -x "$PYTHON" ]]; then
  echo '请先创建 .venv 并安装 pip install -e ".[quickcheck]"，或设置 STUDIO_PYTHON。' >&2
  exit 1
fi
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "请从 evalapp.yaml.example 创建配置文件：$CONFIG_PATH" >&2
  exit 1
fi
if [[ "${STUDIO_BUILD_UI:-0}" == 1 ]]; then
  npm --prefix "$PROJECT_ROOT/report-ui" ci
  npm --prefix "$PROJECT_ROOT/report-ui" run build:studio
fi
exec "$PYTHON" -m evalapp.cli --config "$CONFIG_PATH" studio --port "${STUDIO_PORT:-8766}" "$@"
