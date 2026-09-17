#!/usr/bin/env bash
# 把 Markdown 成品渲染成"打开即可复制"的公众号版页面。
#
# 用法:
#   ./render_wx.sh art-001.md art-002.md        # 默认 default 主题
#   THEME=pie ./render_wx.sh art-001.md         # 换主题
#   PREVIEW_PORT=9000 ./render_wx.sh art-001.md # 换预览端口（默认 8765）
#
# 原理：远端 192.168.100.168（Linux 渲染机）上用 Docker 跑文颜 CLI（Apache-2.0）
# 渲染出全内联样式的 HTML，取回本机后包一层"复制全文"页面，由本机预览服务提供。
#
# 预览服务地址：PREVIEW_HOST / PREVIEW_PORT / PREVIEW_BASE 都可覆盖；
# 默认按本机出口 IP 推导，不写死任何固定机器地址。
set -euo pipefail

HOST=192.168.100.168
THEME="${THEME:-default}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WX="$HERE/wx"
WORK=/tmp/wxrender

PREVIEW_PORT="${PREVIEW_PORT:-8765}"
PREVIEW_HOST="${PREVIEW_HOST:-$(ip -4 route get 1.1.1.1 2>/dev/null \
  | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')}"
PREVIEW_HOST="${PREVIEW_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PREVIEW_HOST="${PREVIEW_HOST:-127.0.0.1}"
PREVIEW_BASE="${PREVIEW_BASE:-http://$PREVIEW_HOST:$PREVIEW_PORT}"

mkdir -p "$WX"
ssh "$HOST" "mkdir -p $WORK"

for src in "$@"; do
  base="$(basename "${src%.md}")"
  scp -q "$src" "$HOST:$WORK/$base.md"
  ssh "$HOST" "cd $WORK && docker run --rm -v $WORK:/w -w /w node:22-alpine \
    npx --yes @wenyan-md/cli render -f $base.md -t '$THEME' > $base.wx-$THEME.html"
  scp -q "$HOST:$WORK/$base.wx-$THEME.html" "$WX/$base.wx.html"
  echo "rendered $base → wx/$base.wx.html (theme=$THEME)"
done

python3 "$HERE/build_wx_pages.py"
echo "打开 $PREVIEW_BASE/wx/ 复制粘贴进公众号后台"
