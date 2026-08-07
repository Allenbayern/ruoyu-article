# Reddit Story 样本说明

当前阶段目标：

- 先用结构稳定的 Reddit JSON 样本打通 `Story Hunter OS` 第一条故事源链路。
- 样本只用于验证字段协议、结构识别和评分骨架，不代表已完成真实在线抓取。

## 当前样本

- `reddit_story_sample_01.json`

## 样本要求

- 保留标题、正文、来源链接、互动数据
- 保留 Top 评论
- 评论暂时可随原样本保存，正式链路中应拆入 `story-vault/comments/reddit/`

## 当前状态

- 目录已建
- 已有首个离线 JSON 样本
- `scripts/reddit_story_fetch.py` / `scripts/reddit_story_collect.py` 已落地
- `scripts/validate_reddit_story_collect.py` 最小验收已 `PASS`
- 当前样本命中 `anonymous_message / object_clue / identity_mystery` 悬疑加权
