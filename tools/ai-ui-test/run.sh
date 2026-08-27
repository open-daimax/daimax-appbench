#!/bin/sh
# AI UI Test Runner
# 自动检查并构建 dist 目录，支持多入口透传执行
#
# 用法:
#   ./run.sh <命令> [参数...]
#
# 命令:
#   test <steps> <assertion>  执行 UI 测试 (主入口)
#   ensure-start-web-server   确保 start-web-server 依赖存在
#   build-schema <url>        将 URL 转换为 schema URL
#
# 示例:
#   ./run.sh test "点击搜索" "搜索成功" --case-id test1
#   ./run.sh ensure-start-web-server
#   ./run.sh build-schema "http://localhost:3000"

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查并构建 dist 目录
if [ ! -d "dist" ]; then
    echo "[run.sh] dist 目录不存在，正在执行构建..."
    [ ! -d "node_modules" ] && npm install
    npm run build
    echo "[run.sh] 构建完成"
fi

# 根据第一个参数决定入口
case "${1:-}" in
    test)
        shift
        exec node dist/command/ai-ui-test.js "$@"
        ;;
    ensure-start-web-server)
        shift
        exec node dist/command/ensure-start-web-server.js "$@"
        ;;
    build-schema)
        shift
        exec node dist/build-schema-cli.js "$@"
        ;;
    "")
        echo "Usage: $0 <command> [args...]"
        echo ""
        echo "Commands:"
        echo "  test <steps> <assertion>  执行 UI 测试"
        echo "  ensure-start-web-server   确保 start-web-server 依赖"
        echo "  build-schema <url>        URL 转 schema"
        exit 1
        ;;
    *)
        echo "Error: Unknown command '$1'"
        echo "Run '$0' without arguments to see usage."
        exit 1
        ;;
esac
