#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATE="${1:-$(date +%F)}"
PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

export ZHIHU_COOKIE="${ZHIHU_COOKIE:-}"
export ZHIHU_COOKIE_FILE="${ZHIHU_COOKIE_FILE:-}"
export DOUBAN_COOKIE="${DOUBAN_COOKIE:-}"
export DOUBAN_COOKIE_FILE="${DOUBAN_COOKIE_FILE:-}"

if [[ -z "$ZHIHU_COOKIE" && -z "$ZHIHU_COOKIE_FILE" && -s "$ROOT/config/private/zhihu_cookie.txt" ]]; then
  export ZHIHU_COOKIE_FILE="$ROOT/config/private/zhihu_cookie.txt"
fi
if [[ -z "$DOUBAN_COOKIE" && -z "$DOUBAN_COOKIE_FILE" && -s "$ROOT/config/private/douban_cookie.txt" ]]; then
  export DOUBAN_COOKIE_FILE="$ROOT/config/private/douban_cookie.txt"
fi

ZHIHU_REAL_RAW="$ROOT/tmp/mediacrawler/zhihu/raw/zhihu_content_raw_real_01.jsonl"
XHS_REAL_RAW="$ROOT/tmp/mediacrawler/xhs/raw/xhs_note_raw_real_01.jsonl"
DOUYIN_REAL_RAW_LATEST="$ROOT/tmp/mediacrawler/douyin/raw/douyin_content_raw_real_latest.jsonl"
DOUYIN_SAMPLE_RAW="$ROOT/media-vault/samples/douyin/douyin_content_raw_real_01.jsonl"
BILIBILI_REAL_RAW_LATEST="$ROOT/tmp/mediacrawler/bilibili/raw/bilibili_content_raw_real_latest.jsonl"
BILIBILI_SAMPLE_RAW="$ROOT/media-vault/samples/bilibili/bilibili_content_raw_real_01.jsonl"
KUAISHOU_SAMPLE_RAW="$ROOT/media-vault/samples/kuaishou/kuaishou_content_raw_sample_01.jsonl"
DOUBAN_GROUP_TOPIC_URL="https://www.douban.com/group/topic/490251781/"

if [[ -s "$ZHIHU_REAL_RAW" ]]; then
  ZHIHU_ARGS=(--zhihu-mediacrawler-input "$ZHIHU_REAL_RAW")
else
  ZHIHU_ARGS=(--zhihu-sample-html "$ROOT/article-vault/samples/zhihu/zhihu_story_sample_02.html")
fi
if [[ -s "$XHS_REAL_RAW" ]]; then
  XHS_INPUT="$XHS_REAL_RAW"
else
  XHS_INPUT="$ROOT/article-vault/samples/xhs/xhs_note_raw_real_01.jsonl"
fi
if [[ -s "$DOUYIN_REAL_RAW_LATEST" ]]; then
  DOUYIN_INPUT="$DOUYIN_REAL_RAW_LATEST"
else
  DOUYIN_INPUT="$DOUYIN_SAMPLE_RAW"
fi
if [[ -s "$BILIBILI_REAL_RAW_LATEST" ]]; then
  BILIBILI_INPUT="$BILIBILI_REAL_RAW_LATEST"
else
  BILIBILI_INPUT="$BILIBILI_SAMPLE_RAW"
fi

"$PYTHON" "$ROOT/scripts/run_daily_pipeline.py" \
  --lane video \
  --date "$DATE" \
  --run-tencent \
  --run-xhs \
  --run-netease-renjian \
  --run-zhihu \
  --run-douban-group \
  --run-toutiao \
  --run-reddit \
  --run-wechat \
  --run-tophub-bilibili-live \
  --run-media-bilibili \
  --run-media-douyin \
  --run-media-kuaishou \
  --tencent-sample-html "$ROOT/samples/tencent-platform/tencent_platform_sample_01.html" \
  --xhs-raw-input "$XHS_INPUT" \
  --netease-renjian-sample-html "$ROOT/story-vault/samples/netease-renjian/renjian_story_sample_01.html" \
  "${ZHIHU_ARGS[@]}" \
  --douban-group-topic-url "$DOUBAN_GROUP_TOPIC_URL" \
  --douban-group-browser \
  --toutiao-sample-html "$ROOT/tests/fixtures/toutiao/story.html" \
  --reddit-sample-json "$ROOT/story-vault/samples/reddit/reddit_story_sample_01.json" \
  --wechat-sample-html "$ROOT/article-vault/samples/wechat/wechat_story_sample_01.html" \
  --media-bilibili-input "$BILIBILI_INPUT" \
  --media-douyin-input "$DOUYIN_INPUT" \
  --media-kuaishou-input "$KUAISHOU_SAMPLE_RAW"
