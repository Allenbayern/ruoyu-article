# vocus Article 样本位

## 用途

用于承接 `vocus.cc` 公开文章样本，优先服务 `Article Vault`，对明显第一人称经历、连载故事、冲突叙事内容可作为 `Story Vault` 补位来源。

## 当前定位

- 主定位：`Article Vault`
- 补位定位：`Story Vault`
- 当前策略：先做公开文章 URL 的离线样本与最小 `fetch / collect / validate`，不碰付费墙，不依赖登录态。
- 当前样本：已覆盖 1 条真实文章向样本、1 条真实故事向样本、1 条第三人称故事样本、1 条真实艺评阻断样本、1 条灰区样本（暂按 `Article Vault`）。
- 当前路由：艺评 / 评论 / 分析型文章默认只进 `Article Vault`；其余内容只要叙事信号足够强，无论第一、第二还是第三人称，都可补进 `Story Vault`。灰区样本当前保守按 `Article Vault` 处理。
- 当前验收：五样本路由验证已 `PASS`。

## 需要用户提供

- 1-3 篇公开 `vocus.cc/article/...` 文章 URL
- 如需批量抓取，再补充目标 `salon` / 作者页 URL
- 如果后续要做列表页采集，再确认是否存在稳定 RSS 或公开列表接口

## 当前已收到的真实文章 URL

- `https://vocus.cc/article/6a22e3aefd89780001aae151`
- `https://vocus.cc/article/6a268fe0fd89780001ab1fac`
- `https://vocus.cc/article/69d8439bfd89780001c350b9`

当前已落样本：

- 文章向：`https://vocus.cc/article/6a29ad46fd89780001f65cf4`
- 故事向：`https://vocus.cc/article/6a2a33f0fd89780001170979`

## 最小样本字段

```json
{
  "source": "vocus",
  "url": "",
  "title": "",
  "author": "",
  "publish_time": "",
  "salon_name": "",
  "tags": [],
  "content": "完整文章原文",
  "content_type": "article",
  "like_count": null,
  "comment_count": null
}
```

## 最小验收

- 标题、作者、发布时间、正文可分离
- 完整原文必须保留
- `salon_name`、`tags` 缺失时允许为空
- 互动字段不可见时显式为 `null`
- 不碰付费墙，不依赖硬编码 cookie
