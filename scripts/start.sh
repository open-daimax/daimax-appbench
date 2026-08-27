#!/bin/bash
# daimax-appbench 启动脚本
# 功能：安装依赖并运行 CLI 评测
#
# 使用方法：
#   安装依赖：        bash scripts/start.sh setup
#   运行评测：        bash scripts/start.sh evaluate --exec-plan plan.yaml

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON=${PYTHON:-python3}
if ! $PYTHON -c "import sys; assert sys.version_info >= (3, 11)" 2>/dev/null; then
    echo "错误：需要 Python >= 3.11"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "=== 创建虚拟环境 ==="
    $PYTHON -m venv .venv
fi

source .venv/bin/activate

install_deps() {
    echo "=== 安装 evalapp ==="
    pip install -e . -q
}

check_config() {
    if [ ! -f evalapp.yaml ]; then
        echo "⚠️  未找到 evalapp.yaml，从模板创建..."
        cp evalapp.yaml.example evalapp.yaml
        echo "请编辑 evalapp.yaml 填入模型 API Key 等配置后重新运行。"
        exit 1
    fi
}

case "${1:-help}" in
    setup)
        install_deps
        echo "✅ 依赖安装完成"
        ;;
    evaluate)
        install_deps
        check_config
        shift
        echo "=== 运行评测 ==="
        evalapp evaluate "$@"
        ;;
    help|*)
        echo "用法: bash scripts/start.sh <命令>"
        echo ""
        echo "命令:"
        echo "  setup      安装依赖"
        echo "  evaluate   运行评测（后跟 evalapp evaluate 参数）"
        echo ""
        echo "示例:"
        echo "  bash scripts/start.sh setup"
        echo "  bash scripts/start.sh evaluate --exec-plan ./plans/v2_web.yaml"
        ;;
esac
