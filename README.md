# Ruoyu Film Daily

This repository contains the controlled-production workflow for the Ruoyu film article group.

## Current state

- Phase 1 contract and internal templates exist.
- Phase 2 offline validators and synthetic negative tests exist.
- The next permitted operation is one manually initiated, real-source controlled batch that stops at `R8 review-ready`.
- No cron, source registry, publisher integration, message delivery, HTML renderer, image pipeline, or publication path is implemented or authorized.

## First-run boundary

Use [controlled-first-run-brief.md](templates/controlled-first-run-brief.md) as the task contract. The run must stop after independent review handoff. A green local validator confirms only deterministic batch gates; it does not establish factual truth, article quality, `publish-ready`, or publication authorization.

## Offline verification

```bash
python3 -m pytest -q
```

The tests use synthetic records only. They verify state transitions, slot and angle separation, claim-coverage requirements, withheld HTML, and the no-publication boundary.

## Manual Toutiao evidence capture

The public Toutiao adapter captures one explicit article URL into an explicit local
run root. It fetches the official mobile page without cookies, proxies, browser
automation, JavaScript execution, or anti-bot bypass. A successful command writes
only `sources/<source-id>.txt` and prints one source-manifest entry; it does not
select a candidate, create an article, advance a workflow state, or publish.

```bash
uv run python -m article_group.toutiao_cli \
  --url 'https://www.toutiao.com/article/<article-id>/' \
  --run-root runs/2026-08-01/controlled-001 \
  --source-id TT-<article-id> \
  --independence-group toutiao:<article-id>
```

## Yuafeng hot-list discovery adapter

The read-only Yuafeng adapter fetches trending-list data from
api-v2.yuafeng.cn. Every result is discovery-only (never evidence).

```python
from article_group.yuafeng_hot import fetch_uc_hot, fetch_tencent_news, fetch_aggregate

# UC hot list
result = fetch_uc_hot()

# Tencent news with optional page and type
result = fetch_tencent_news(page=1, type_="hot")

# Aggregate — one of: 知乎热榜, 微博热榜, 微信热文榜, 澎湃热榜,
#                     百度热点, 知乎日报, 今日头条热榜, 梨视频总榜
result = fetch_aggregate("微博热榜")
```

The API key is read from the `YUAFENG_API_KEY` environment variable at
call-time. It is never persisted, logged, or included in exception messages.

The command returns exit code `2` and emits JSON on stderr when the public static
page is unavailable, challenged, unsupported, or the local snapshot is invalid.
