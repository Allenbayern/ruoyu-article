#!/bin/bash
# DailyHot 热榜抓取快捷脚本
# 用法：./dailyhot-run.sh [选项]
# 快捷方式：./dailyhot-run.sh           → 全部源+生成报表
#          ./dailyhot-run.sh movie      → 只抓豆瓣电影
#          ./dailyhot-run.sh dry        → 试运行不保存

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/dailyhot-fetch.py"
OUTPUT_DIR="$(dirname "$SCRIPT_DIR")/research-daily"

cd "$(dirname "$SCRIPT_DIR")/.."  # 回到 workspace 根目录

case "${1:-all}" in
    movie)
        python3 "$PYTHON_SCRIPT" --source douban-movie --format hotspot-report
        ;;
    full|all)
        python3 "$PYTHON_SCRIPT" --format hotspot-report
        ;;
    dry)
        python3 "$PYTHON_SCRIPT" --dry-run --format hotspot-report
        ;;
    quick)
        python3 "$PYTHON_SCRIPT" --source douban-movie,weibo,bilibili,douyin --limit 15 --format hotspot-report
        ;;
    json)
        python3 "$PYTHON_SCRIPT" --format json
        ;;
    *)
        echo "用法：$0 [movie|full|dry|quick|json]"
        echo "  movie - 仅豆瓣电影"
        echo "  full  - 全部数据源"
        echo "  dry   - 试运行（不保存）"
        echo "  quick - 快速模式（4核心源）"
        echo "  json  - JSON格式输出"
        ;;
esac
