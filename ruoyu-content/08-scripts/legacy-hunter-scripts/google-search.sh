#!/bin/bash
# Google Custom Search wrapper for hotspot-hunter
# Usage: ./google-search.sh "关键词" [结果数]
# Outputs JSON to stdout

API_KEY="AIzaSyB3P_FIXi81KXQOeWKOV6KJd6w61ZSwu8c"
CX="418c686055e7342df"
QUERY="${1:-}"
NUM="${2:-10}"
OUTDIR="${3:-employees/research-daily}"

if [ -z "$QUERY" ]; then
  echo '{"error":"missing query"}' >&2
  exit 1
fi

# URL-encode the query
ENCODED_QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$QUERY'))")

RESULT=$(curl -s --connect-timeout 10 \
  "https://www.googleapis.com/customsearch/v1?key=${API_KEY}&cx=${CX}&q=${ENCODED_QUERY}&num=${NUM}&lr=lang_zh-CN" \
  -H "User-Agent: OpenClaw-HotspotHunter/1.0")

# Check for errors
if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if 'items' in d else 1)" 2>/dev/null; then
  echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [])
results = []
for item in items:
    results.append({
        'title': item.get('title',''),
        'link': item.get('link',''),
        'snippet': item.get('snippet',''),
        'displayLink': item.get('displayLink','')
    })
print(json.dumps({'query': '$QUERY', 'total': len(results), 'results': results}, ensure_ascii=False))
"
else
  echo "$RESULT"
fi
