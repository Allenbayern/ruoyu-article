# 小红书 Story 样本位

## 用途

用于承接小红书笔记正文样本，并明确哪些正文允许补进 `Story Vault`。

## 当前状态

- 已真实确认 `MediaCrawler xhs detail_contents.jsonl` 可产出正文 JSONL。
- 已实查真实输出文件：`external/mediacrawler/data/xhs/jsonl/detail_contents_2026-06-11.jsonl`。
- 已固定首份真实正文 raw 落点：`projects/media-intel-aios/tmp/mediacrawler/xhs/raw/xhs_note_raw_real_01.jsonl`。
- 已归档首份真实正文 raw：`projects/media-intel-aios/article-vault/samples/xhs/xhs_note_raw_real_01.jsonl`。
- 已归档首份真实 `Story Vault` leads：`projects/media-intel-aios/story-vault/samples/xhs/xhs_note_story_leads_real_01.jsonl`。
- 已新增最小正文链路：
  - `projects/media-intel-aios/scripts/mediacrawler_xhs_note_normalize.py`
  - `projects/media-intel-aios/scripts/xhs_note_collect.py`
  - `projects/media-intel-aios/scripts/validate_xhs_note_collect.py`
- 已新增联动验收：`projects/media-intel-aios/scripts/validate_xhs_note_comment_joint.py`
- 已用 3 条真实 `xhs` 笔记 detail 输出跑通项目侧最小验收：`normalized_count=3`、`article_count=3`、`story_count=2`。

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

## 当前路由口径

- 正文默认先进入 `Article Vault`。
- 只有正文存在明确关系、经历、冲突、情绪推进信号时，才允许补 `Story Vault`。
- `攻略 / 教程 / 盘点 / 测评 / 清单 / 文案 / 技巧 / 方法 / 认知提升` 这类方法论表达，只进 `Article Vault`。

## 最小验收

- 能保留完整笔记正文
- 能关联原始 `note_id / url`
- 不用摘要替代正文
- `Story Vault` 路由必须保守，不默认双发
