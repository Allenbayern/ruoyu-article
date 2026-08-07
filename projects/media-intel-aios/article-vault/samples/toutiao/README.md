# 今日头条 Article 样本位

## 用途

用于承接今日头条文章样本，先验证 Article Vault 字段协议，再接 Playwright 页面抓取。

## 当前状态

- 已落首个真实故事向 HTML 样本：`toutiao_story_sample_01.html`
- 已落首个真实影视评论 / 艺评 HTML 样本：`toutiao_review_sample_02.html`
- 已落第二批灰区样本：`toutiao_grayzone_sample_03.html`
- 已有最小 `fetch / collect / validate` 链路
- 当前验收：`validate_toutiao_collect.py` 已 `PASS`
- 当前灰区结论：`剧情解读 / 角色分析` 型长文，即使带人物冲突和关系戏，当前仍暂按 `Article Vault` 处理

## 路由口径

- 默认先按 `Article Vault` 理解。
- 艺评、评论、评析、行业分析、观察类长文，默认只进 `Article Vault`。
- 不因为正文里出现人物、真相、主角、父母、关系这类叙事词，就自动补进 `Story Vault`。
- 只有正文具备明确叙事推进、人物关系、冲突变化、反转结果时，才补 `Story Vault`。

## 需要用户提供

- 1-3 篇目标文章 URL
- 目标账号或关键词
- 是否只做文章正文，还是同步评论字段

## 最小样本字段

```json
{
  "source": "toutiao",
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

- 标题、正文、作者、URL 可分离
- 至少一个互动字段可用；不可见则显式为 `null`
- 如同步评论，评论必须进入 Comment Vault，不混入文章正文
