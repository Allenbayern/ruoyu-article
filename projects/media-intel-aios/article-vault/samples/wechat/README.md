# 微信公众号 Article 样本位

## 用途

用于承接微信公众号爆文样本，优先走搜狗微信入口或指定文章 URL 的 Playwright 样本验证。

## 路由口径

- 默认先按 `Article Vault` 理解。
- 艺评、评论、评析、行业分析、观察类长文，默认只进 `Article Vault`。
- 不因为正文里出现人物、真相、主角、父母、关系这类叙事词，就自动补进 `Story Vault`。
- 只有正文具备明确叙事推进、人物关系、冲突变化、反转结果时，才补 `Story Vault`。

## 需要用户提供

- 目标公众号列表
- 搜狗微信关键词
- 可复用浏览器态
- 1-3 篇文章 URL 或历史样本 HTML

## 最小样本字段

```json
{
  "source": "wechat",
  "account_name": "",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "content": "完整文章原文",
  "read_count": null,
  "like_count": null,
  "comment_count": null
}
```

## 最小验收

- 标题、账号、正文可分离
- 完整原文必须保留
- 互动字段不可见时显式为 `null`
- 不依赖硬编码 cookie
