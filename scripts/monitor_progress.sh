#!/bin/bash
# 自动监控脚本 - 每10分钟检查一次Claude评测进度

BASE_DIR="${EVAL_APP_FACTORY:-$HOME/eval_app_factory}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPTIMIZATION_FILE="$SCRIPT_DIR/../OPTIMIZATION_RECORD.md"

# 支持命令行参数或环境变量指定日志文件和工作区目录，未指定则自动检测最新
LOG_FILE="${MONITOR_LOG_FILE:-}"
WORKSPACE="${MONITOR_WORKSPACE:-}"

if [ -z "$LOG_FILE" ]; then
    LOG_FILE=$(ls -t "$BASE_DIR"/claude_eval_log_*.txt 2>/dev/null | head -1)
fi
if [ -z "$WORKSPACE" ]; then
    WORKSPACE=$(ls -d "$BASE_DIR"/claude_*/ 2>/dev/null | sort -r | head -1)
    # 去除尾部斜杠
    WORKSPACE="${WORKSPACE%/}"
fi

echo "开始监控Claude评测进度..."

while true; do
    CURRENT_TIME=$(date '+%Y-%m-%d %H:%M')
    
    # 检查日志文件
    if [ -f "$LOG_FILE" ]; then
        # 获取最后30行日志
        LAST_LOGS=$(tail -30 "$LOG_FILE")
        
        # 提取关键信息
        CURRENT_SAMPLE=$(echo "$LAST_LOGS" | grep "Evaluating" | tail -1 | sed 's/.*Evaluating /正在评测: /')
        
        # 检查是否有进度更新
        if echo "$LAST_LOGS" | grep -q "Test execution complete"; then
            LAST_RESULT=$(echo "$LAST_LOGS" | grep "Test execution complete" | tail -1)
            echo "[$CURRENT_TIME] $CURRENT_SAMPLE - $LAST_RESULT" >> "$OPTIMIZATION_FILE"
        fi
        
        if echo "$LAST_LOGS" | grep -q "Sample evaluation complete"; then
            FINAL_RESULT=$(echo "$LAST_LOGS" | grep "Sample evaluation complete" | tail -1)
            echo "[$CURRENT_TIME] Claude评测完成: $FINAL_RESULT" >> "$OPTIMIZATION_FILE"
            echo "[$CURRENT_TIME] Claude评测已完成"
            break
        fi
    else
        echo "[$CURRENT_TIME] 日志文件尚未创建" >> "$OPTIMIZATION_FILE"
    fi
    
    # 等待10分钟
    sleep 600
done

echo "监控结束"
