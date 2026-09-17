#!/usr/bin/env bash
# 把某期 run 的"公众号复制版"同步到本机预览站。
#
# 用法:
#   ./sync_wx.sh 2026-09-16/daily-008
#   ./sync_wx.sh            # 同步最近一期
#
# run 侧已经由 daily 引擎的 wechat_render 步骤自动生成
#（runs/<date>/daily-00N/wechat/，含复制页/源码/索引/manifest），
# 这里只负责把它们搬到本机预览站（默认 http://<本机IP>:8765/wx/，见 PREVIEW_BASE）。
#
# 2026-09-17：预览站已归 Linux 本机。原先的 ssh/scp 到 192.168.100.168 现在
# 等于自己连自己，改为本地文件拷贝，不再依赖 ssh，也不再写死 /home/allen 前缀。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)/runs"
WX="$HERE/wx"

PREVIEW_PORT="${PREVIEW_PORT:-8765}"
PREVIEW_HOST="${PREVIEW_HOST:-$(ip -4 route get 1.1.1.1 2>/dev/null \
  | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')}"
PREVIEW_HOST="${PREVIEW_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PREVIEW_HOST="${PREVIEW_HOST:-127.0.0.1}"
PREVIEW_BASE="${PREVIEW_BASE:-http://$PREVIEW_HOST:$PREVIEW_PORT}"

run="$1"
if [ -z "$run" ]; then
  run="$(ls -d "$REPO"/*/daily-*/ 2>/dev/null | sort | tail -1)"
  run="$(basename "$(dirname "$run")")/$(basename "$run")"
  echo "未指定 run，使用最近一期：$run"
fi

SRC="$REPO/$run/wechat"
[ -d "$SRC" ] || { echo "未找到 $run 的 wechat 产物（run 是否跑过 wechat_render 步骤？）" >&2; exit 1; }

mkdir -p "$WX"
cp -f "$SRC"/*.html "$SRC"/manifest.json "$WX/"
rm -f "$WX"/*.pie.html "$WX"/*.bak
echo "已同步 $run → $WX/"
echo "打开 $PREVIEW_BASE/wx/ 复制粘贴进公众号后台"
