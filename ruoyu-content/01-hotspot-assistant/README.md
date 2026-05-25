# 本地热点助手

## 定位

替代原 NAS 热点猎手。以后不再从 `192.168.100.223:8888/handover-hotspot/` 获取任务结果。

热点助手只做本地采集与整理：

- 每日热点扫描
- 有效正文语料抓取
- 事实锚点提取
- 影视桥段/电影资料补充
- 输出每日选题池

## 新工具接入

- 微信公众号文章：优先使用 `weixin-reader__read_weixin_article`，用于读取公众号正文、拆爆款案例、补充竞品素材。
- 难抓网页：轻量 fetch 失败后再用 Scrapling；适合普通 fetch 抓不到的新闻、影评、轻度反爬页面。
- 大批量抓取/案例总结/粗稿：交给 Reasonix / DeepSeek，GPT 不搬砖。

详细规则见：`tool-and-source-policy.md`

## 输出位置

- 每日简报：`../02-research-daily/YYYY-MM-DD.md`
- 正文语料：`../03-article-corpus/`
- 抓取失败：`../03-article-corpus/errors/`
- 当前给写手的大纲：`../04-plans/HOT_SPOT_PLAN.md`
- 已推荐选题记录：`../07-data/topic-ledger.md`

## 硬要求

- 不交空选题。
- 不只搬热榜。
- 每个推荐选题必须有事实锚点。
- 每个影视交叉选题必须有电影桥段锚点。
- 抓不到有效正文就标注“素材不足”。
- 已给过用户的选题默认不重复推荐；强热点重写必须换角度。
