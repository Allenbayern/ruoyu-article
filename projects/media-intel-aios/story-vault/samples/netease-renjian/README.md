# 网易人间 Story 样本位

## 用途

用于承接网易人间文章样本。优先核验 RSS；RSS 不足时用 Playwright / 页面抓取兜底。

## 当前状态

- 已落首个真实 HTML 样本：`renjian_story_sample_01.html`
- 已有最小 `fetch / collect / validate` 链路
- 当前验收：`validate_netease_renjian_collect.py` 已 `PASS`

## 需要用户提供

- 指定栏目 URL 或 RSS 地址（如有）
- 1-3 篇目标文章 URL
- 是否接受 `RSS 摘要 + 页面正文兜底` 的混合链路

## 最小样本字段

```json
{
  "source": "netease_renjian",
  "article_id": "",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "summary": "",
  "content": "完整文章原文",
  "tags": []
}
```

## 最小验收

- RSS 可用时优先保留 RSS 原始 item
- 页面正文可用时保留完整正文
- 若 RSS 只有摘要，必须标明 `content_status=summary_only`
