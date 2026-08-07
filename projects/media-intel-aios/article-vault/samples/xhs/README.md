# 小红书 Article 样本位

## 用途

用于承接小红书笔记正文样本，并固定 `MediaCrawler xhs detail` 进入 `Article Vault` 的真实基线。

## 当前状态

- 已真实确认 `MediaCrawler xhs detail_contents.jsonl` 可产出正文 JSONL
- 已固定首份真实正文 raw：`projects/media-intel-aios/article-vault/samples/xhs/xhs_note_raw_real_01.jsonl`
- 已固定首份真实 `Article Vault` leads：`projects/media-intel-aios/article-vault/samples/xhs/xhs_note_article_leads_real_01.jsonl`
- 当前真实结果：3 条 note 全部进入 `Article Vault`

## 最小样本字段

```json
{
  "source": "xhs",
  "note_id": "",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "content": "完整笔记原文",
  "like_count": 0,
  "collect_count": 0,
  "comment_count": 0,
  "share_count": 0,
  "tags": []
}
```

## 最小验收

- 保留完整正文
- 能关联 `note_id / url`
- 不用摘要替代正文
- 默认进入 `Article Vault`
