# 豆瓣 Article 样本位

## 用途

用于承接豆瓣影评 / 长评 / 评论型正文的离线样本，优先服务 `Article Vault`。

## 当前定位

- 主定位：`Article Vault`
- 当前策略：先做公开影评 HTML 的离线样本与最小 `fetch / collect / validate`，不依赖登录态。
- 当前样本：已覆盖 1 条真实影评样本。
- 当前路由：影评 / 长评 / 解析型正文默认只进 `Article Vault`。
- 当前验收：单样本验证已 `PASS`。

## 需要用户提供

- 1-3 篇公开豆瓣影评 / 长评 HTML
- 如后续要接讨论帖，再补豆瓣小组或讨论串样本

## 最小样本字段

```json
{
  "source": "douban",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "content": "完整影评原文",
  "content_type": "article"
}
```

## 最小验收

- 标题、作者、发布时间、正文可分离
- 完整原文必须保留
- 默认不进 `Story Vault`
