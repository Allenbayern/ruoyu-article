# 知乎 Story 样本位

## 用途

用于承接知乎问题 / 回答 / 评论的离线样本，先验证 Story Vault 字段协议，再接 Playwright 登录态采集。

## 当前状态

- 已落 1 条真实分析回答样本：默认只进 `Article Vault`
- 已落 1 条真实故事回答样本：可进入 `Article Vault` + `Story Vault`
- 已有最小 `fetch / collect / validate` 链路
- 当前验收：双样本验证已 `PASS`

## 需要用户提供

- 1-3 个知乎问题 URL
- 可复用登录态：浏览器 profile、cookie 导出，或已登录 OpenClaw 节点浏览器
- 优先关键词：`真实故事`、`婚姻`、`反转`、`悬疑`、`家庭秘密`

## 最小样本字段

```json
{
  "source": "zhihu",
  "question_id": "",
  "answer_id": "",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "content": "完整回答原文",
  "vote_count": 0,
  "favorite_count": 0,
  "comments": []
}
```

## 最小验收

- 能保留完整问题标题和回答原文
- 能关联原始 URL
- 至少一个互动字段可用；不可见则显式为 `null`
- 如评论可见，至少保留 3 条评论
