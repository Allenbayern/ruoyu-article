# 腾讯视频片单样本说明

当前阶段目标：

- 为 `腾讯视频片单页` 建立可复用的本地样本位。
- 先跑通本地 HTML 验证，再补正式 `fetch / collect` 骨架。

## 建议样本类型

优先保存以下任一种公开页面源码：

- 年度片单页
- 待播剧 / 待播综艺页
- 站内专题片单页
- 平台项目储备展示页

## 文件命名建议

- `tencent_platform_sample_01.html`
- `tencent_platform_sample_02.html`

## 保存要求

- 直接保存浏览器“查看源代码”或完整 HTML
- 保留页面中的作品名、平台标签、时间字段、简介块、链接块
- 如页面为 SPA，可优先保存渲染后 HTML

## 当前状态

- 目录已建
- 当前已有 `tencent_platform_sample_01.html`
- `scripts/validate_tencent_platform.py` 已对该样本验证 `PASS`
- 当前已补 `scripts/tencent_platform_fetch.py` 与 `scripts/tencent_platform_collect.py` 作为正式骨架
