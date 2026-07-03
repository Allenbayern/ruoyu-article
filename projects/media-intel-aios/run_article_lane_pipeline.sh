#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATE="${1:-$(date +%F)}"
PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

"$PYTHON" "$ROOT/scripts/run_daily_pipeline.py" \
  --lane article \
  --date "$DATE" \
  --run-dumou \
  --run-news-fallback \
  --run-guduo \
  --run-vocus \
  --run-xiniu \
  --run-douban \
  --run-hotboard \
  --run-tophub \
  --guduo-date "2026-06-09" \
  --guduo-offline-dir "$ROOT/samples/guduo" \
  --vocus-sample-json "$ROOT/article-vault/samples/vocus/vocus_article_sample_01.json" \
  --douban-sample-html "$ROOT/article-vault/samples/douban/douban_review_sample_01.html" \
  --hotboard-sample-json "$ROOT/hotboard/samples/hotlist_web_sample_01.json"
