# 豆瓣小组 Story 样本位

## 用途

用于承接豆瓣小组讨论帖 / 求助帖 / 关系帖的离线样本，优先服务 `Story Vault`。

## 当前定位

- 主定位：`Story Vault`
- 补位定位：`Article Vault`
- 当前策略：先做公开讨论帖 HTML 的离线样本与最小 `fetch / collect / validate`，不依赖登录态。
- 当前样本：已覆盖 2 条真实讨论帖故事样本。
- 当前路由：讨论帖正文默认进入 `Article Vault` + `Story Vault`；热评单独保留在样本记录中。
- 当前验收：双样本验证已 `PASS`。

## 需要用户提供

- 1-3 篇公开豆瓣小组讨论帖 HTML
- 如果后续要补更强评论层，再继续给更完整页面样本

## 最小样本字段

```json
{
  "source": "douban_group",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "content": "完整帖子正文",
  "content_type": "story",
  "comment_count": 0,
  "hot_comment_count": 0,
  "comments": []
}
```

## 最小验收

- 标题、作者、发布时间、正文可分离
- 完整帖子原文必须保留
- 至少可提取 3 条热评
- 正文默认进入 `Story Vault`
