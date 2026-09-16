# 谈资型发现源调研与规划建议（2026-09-16）

> 用途：为 R0 发现层扩展（豆瓣小组/小红书等谈资型版面）提供方案对比与分步路径。
> 状态：调研结论，未落地实现；接入动作待 controller 拍板。
> 边界：全部信号只作选题发现（R0），不作事实来源；观众观点类信号不能升级为
> reported_feature 的证据角色。

## 核心结论

- 现成的谈资信号集中在 **DailyHotApi**（豆瓣小组"讨论精选"/贴吧热议/虎扑步行街/
  NGA/知乎/头条热榜，Docker 零成本，豆瓣端点免登录可用）；
- **小红书是最大空白且爬虫有硬合规红线**（2025 年两起判例：上海知产法院判赔 110 万、
  杭州中院判赔 490 万，绕反爬=不正当竞争）——只能人工用官方后台/第三方 SaaS；
- "立场分化/讨论密度"**全行业无现成输出，必须自建 LLM 分类层**（可用现有雷达的
  LLM 能力）。

## 实测端点（2026-09 本机 curl）

| 端点 | 状态 |
|------|------|
| douban.com/group/explore（小组讨论精选，30 条跨组热帖） | ✅ 免登录 200 |
| movie.douban.com/j/subject_suggest | ✅ 免 key 可用 |
| toutiao.com/hot-event/hot-board | ✅ 公开 JSON |
| weibo.com/ajax/side/hotSearch / m.weibo.cn 热榜 | ⚠️ 403/432，需 cookie+国内住宅 IP |
| api.douban.com/v2 | ❌ apikey 申请已关闭多年，公开 key 已封 |

## 方案对比（摘要）

| 方案 | 信号质量 | 成熟度 | 成本 | 维护 | 合规 | 接入建议 |
|------|---------|--------|------|------|------|---------|
| DailyHotApi（imsyy，4k⭐，含 48 路由） | 中高 | 高 | 0 | 低 | 低 | ✅ 第一步 |
| 豆瓣 group/explore 直采（兜底） | 中高 | 高 | 0 | 低 | 低-中（低频只读） | ✅ 兜底 |
| douban_group_spy（110⭐，2024 停更） | 中 | 半成品 | 0 | 中 | 低-中 | 参考 |
| MediaCrawler（65k⭐，小红书/微博/贴吧/知乎评论语料） | 高 | 框架高、合规自担 | 0 | 高 | **高（判例红线）** | ⚠️ 第三步有条件 |
| 千瓜/新红/蝉小红 | 中-高 | 商业成熟 | 150-800 元/月 | 0 | 保密协议禁传播"预估数据"、无自托管 API | ❌ 仅人工 |
| 小红书开放平台/蒲公英/聚光 | 官方最准 | 官方 | 企业资质门槛 | 0 | 最低 | ❌ 个人不满足资质 |
| 新榜/清博 | 高 | 成熟 | 年费数千-数万 | 0 | 低 | ❌ 超预算 |
| 微博热搜/超话 | 中高 | 半成品 | 低 | 高（cookie/风控） | 中 | ⚠️ 第二步候选 |
| 微信指数/百度指数 | 中 | 低（无官方 API，易碎） | 0 | 高 | 中 | ❌ 不碰 |
| 即刻圈子 | 中 | 低（无 API，需逆向） | 0 | 高 | 中 | ❌ 人工看 |

## 三步推荐路径（每步含验收标准）

**第 1 步（0 成本，1-2 天）**：Linux 主机 Docker 部署 DailyHotApi，只开
douban-group/tieba/hupu/ngabbs/zhihu/toutiao 路由（微博需国内 IP 时再开），写薄适配器
把 JSON 灌入现有雷达存储或作只读 API。
验收：连续 7 天 douban-group 路由每日 ≥20 条当日新帖、标题/链接有效、无人工干预
成功率 ≥95%、每条可回溯豆瓣原帖。

**第 2 步（验证谈资价值，1-2 周）**：自建"争议度/立场"粗分类层（LLM 对标题+摘要
打分），人工抽评；同时人工试用蝉小红 1 个月（150-400 元/月档）验证话题趋势/评论
热词能否提升选题命中率。
验收：50 个候选信号人工评审可成当日选题 ≥20%；立场分类与人工一致率 ≥70%；
试用期产出 ≥3 个靠热词信号发现的已发布选题。

**第 3 步（有条件扩展）**：仅在前两步通过后，用独立小号 + MediaCrawler 对小红书
指定影视关键词做低频采集（每日 1 次、top50 笔记+二级评论），本地 LLM 立场聚类；
出现风控立即停用回退蝉小红人工流。
验收：两周采集成功率 ≥80% 且无风控；聚类出的争议点/共鸣点被 ≥3 个选题实际引用；
否则永久回退。

**明确不碰**：微信/百度指数、即刻、微博超话爬虫、任何转售/公开数据集、小红书
规模化爬虫、豆瓣官方 apikey、千瓜/新红/蝉小红的 API 化。

## 合规要点

- 小红书：官方明确禁止爬取（官方声明 + 两起判例）；替代 = 官方创作者后台/蒲公英
  （免费）+ 蝉小红人工查询；
- 豆瓣：官方 API 实质关闭；页面端点低频只读（DailyHotApi 做法）风险低，勿高频勿转售；
- 微博：非官方抓取需 cookie，建议仅依赖 DailyHotApi 的 weibo 路由 + 国内住宅 IP。

## 主要来源

- DailyHotApi：https://github.com/imsyy/DailyHotApi（douban-group 路由源码
  src/routes/douban-group.ts；部署教程 https://www.cpolar.com/blog/step-by-step-guide-to-deploying-dailyhot-build-your-own-trending-list-dashboard）
- MediaCrawler：https://github.com/NanmiCoder/MediaCrawler；爬虫判例合集
  https://github.com/HiddenStrawberry/Crawler_Illegal_Cases_In_China
- 小红书判例与官方 API：https://www.jizhil.com/xhsdata/14404.html；反作弊声明
  https://finance.eastmoney.com/a/202606103767078566.html
- 豆瓣 API 现状：https://github.com/KeyRotate/LibreTV-App/blob/main/douban_apis.md；
  apikey 停止申请 https://www.zhihu.com/question/38829927
- 豆瓣小组爬虫参考：https://github.com/lesywix/douban_group_spy
- 千瓜保密协议：https://www.qian-gua.com/appfile/dataconfidentialityagreement
- 小红书数据工具价格对比：https://insight.xiaoduoai.com/e-commerce-information/how-to-measure-the-effect-of-grass-growing-notes-which-tool-has-the-most-accurate-data-comparison-and-recommendation-of-5-affordable-high-traffic-platforms.html
- 实测端点：https://www.douban.com/group/explore、
  https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
