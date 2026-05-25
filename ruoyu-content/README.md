# 若雨随影｜本地内容工作区

> 从 2026-05-26 起，不再依赖 NAS 热点猎手和 `192.168.100.223` 交接目录。所有热点采集、语料、选题、大纲、初稿、终稿统一放在本地 OpenClaw 工作区。

## 目录约定

- `00-inbox/`：老板临时投喂的数据、链接、截图说明。
- `01-hotspot-assistant/`：新本地热点助手的任务书、规则、运行记录。
- `02-research-daily/YYYY-MM-DD.md`：每日热点简报、选题池、推荐优先级。
- `03-article-corpus/`：正文语料库。
  - `film/`：影视/影评/片单正文。
  - `social/`：社会热点事实源正文。
  - `reference/`：电影资料、导演访谈、背景资料。
  - `errors/`：抓取失败记录。
- `04-plans/HOT_SPOT_PLAN.md`：给 Reasonix 写手使用的硬核大纲。按需覆盖当前任务。
- `05-drafts/draft_article.txt`：Reasonix / DeepSeek-V4-Flash 扩写初稿。
- `06-final/`：OpenClaw 终审抛光后的终稿。
- `07-data/`：头条、公众号、收益、阅读量等数据表。
- `08-scripts/`：本地采集脚本和配置。
- `09-archive/`：旧 NAS/handover 资料归档。
- `10-case-library/`：爆款案例库、培训材料、写作标准。

## 当前三步流水线

1. OpenClaw 只出选题判断 + 事实锚点 + 电影桥段锚点 + 硬核大纲，保存为 `04-plans/HOT_SPOT_PLAN.md`。
2. Reasonix / DeepSeek-V4-Flash 吃素材和大纲，生成 `05-drafts/draft_article.txt`。
3. OpenClaw 做终审：去AI腔、砍空话、打磨开头结尾和冷酷金句，输出到 `06-final/`。
