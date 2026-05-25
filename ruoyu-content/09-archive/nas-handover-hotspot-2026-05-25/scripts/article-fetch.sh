#!/bin/bash
# 爆文素材抓取快捷脚本
# 用法：./article-fetch.sh [50|100|200|dry|google]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/article-fetcher.py"

cd "$(dirname "$SCRIPT_DIR")/.."  # 回到 workspace 根目录

case "${1:-50}" in
    dry)
        echo "🔍 试运行模式（仅发现，不抓正文）"
        python3 "$PYTHON_SCRIPT" --dry-run --limit 50
        ;;
    google)
        echo "📡 仅Google搜索模式"
        python3 "$PYTHON_SCRIPT" --source google --limit 30
        ;;
    zhihu)
        echo "📡 仅知乎热榜模式"
        python3 "$PYTHON_SCRIPT" --source zhihu --limit 20
        ;;
    50|100|200)
        echo "📰 全量抓取 $1 篇"
        python3 "$PYTHON_SCRIPT" --limit "$1"
        ;;
    *)
        echo "用法：$0 [50|100|200|dry|google|zhihu]"
        echo "  50/100/200  - 目标文章数"
        echo "  dry         - 试运行（仅发现）"
        echo "  google      - 仅Google搜索"
        echo "  zhihu       - 仅知乎"
        ;;
esac

# 显示今日成果
TODAY=$(date +%Y-%m-%d)
CORPUS_DIR="employees/article-corpus/$TODAY"
if [ -f "$CORPUS_DIR/metadata.json" ]; then
    echo ""
    echo "📊 今日素材统计："
    python3 -c "
import json
with open('$CORPUS_DIR/metadata.json') as f:
    d = json.load(f)
print(f'  总计：{d[\"total\"]} 篇')
for src, count in d.get('sources', {}).items():
    print(f'  {src}: {count} 篇')
"
fi
