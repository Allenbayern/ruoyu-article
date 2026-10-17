# 自媒体与内容生产工具考察与落地记录

> 记录时间：2026-10-17
> 考察来源：微信公众号优质内容分享（4 篇文章链接评估）

---

## 1. 考察文章与项目清单

| 文章序号 | 主题 / 链接 | 涉及项目 / 工具 | 核心价值评估 | 采纳决策 |
|---|---|---|---|---|
| **文章 1** | `n4wkrmxPtZomKApsw1BCPg`<br>《AI写的东西出厂自带隐形记号...》 | `guillaumemeyer/watermarks-remover`<br>(~23k star) | 清洗 AI 隐形零宽字符（U+200B/U+200C/U+2060等）与元数据。 | **✅ 核心逻辑落地进现有门禁**：无缝升级 `anti_ai_gate.py` 和 `dna_engine.py`，实现零宽字符扫描与剥离。 |
| **文章 2** | `NzqGnbrgvIMtY2VXHIO9CA`<br>《一个软件吞掉一整个自媒体运营部...》 | `Jamailar/Beav`<br>(Tauri+Rust 本地工作台) | 小红书卡片墙、本地优先、评论区洞察转选题、文档式粗剪。 | **⚠️ 暂不引入桌面端**：本地已有完备 DSH + Obsidian + WeRss 架构；其“评论区争议提炼选题”思路在 `ruoyu-sijiantao` / `hot-trend-radar` 中已实现。 |
| **文章 3** | `zkZuXzzaMU503-dyqDswXQ`<br>《9.8K star！一款杀疯了的抖音批量下载工具...》 | `jiji262/douyin-downloader`<br>(~9.8k star) | 抖音/TikTok/YouTube 批量无水印下载、合集/主页抓取、直播录制、REST API。 | **⭐ 高价值工业备选**：相比现有 `catbus` 单条/基础提取，此项目更适合大规模全量素材库归档，已沉淀使用指南备查。 |
| **文章 4** | `b3b-M44PVlURZoXhCWgwOA`<br>《写公众号的辅助工具...》 | 微信指数、易撰、豆包 | 基础新手工具（查词、查重、AI改写）。 | **❌ 略过**：属于初阶科普；易撰查重远弱于我们的朱雀+12篇母本门禁；豆包文风不符合若雨要求。 |

---

## 2. 落地成果：anti_ai_gate 隐形字符扫描与清洗防御

### 2.1 风险背景
部分 LLM API 或生成式服务在输出文本时，会夹带不可见字符（如零宽空格、零宽非连接符、Word Joiner 等）作为溯源或隐形标记。

### 2.2 门禁实现
在 `/home/allen/Projects/ruoyu-film-daily/article_group/anti_ai_gate.py` 中新增：
- `ZERO_WIDTH_CHARS`：定义常见零宽字符（`U+200B`, `U+200C`, `U+200D`, `U+2060`, `U+FEFF`）。
- `scan_invisible_watermarks(text)`：精确统计隐形字符并记录定位与上下文。
- `clean_invisible_watermarks(text)`：确定性清洗剥离所有隐形标记。
- `check_anti_ai(text)`：**一票否决制**——若正文中检出任何未清洗的隐形零宽字符，门禁直接判定 `passed = False`。
- `dna_engine.py` 联动：将隐形水印列入母本 DNA 审计的硬违规项（violations）。

### 2.3 测试验证
- `tests/test_anti_ai_gate.py` 增加 `test_invisible_watermarks_detection_and_cleaning` 测试用例；
- 12 项测试全部通过（12 passed in 1.35s）。

---

## 3. 备选武器库：`douyin-downloader` 接入备忘

- **项目主页**：[https://github.com/jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader)
- **典型用法**：
  ```bash
  # 快速批量下载博主无水印视频
  git clone https://github.com/jiji262/douyin-downloader
  pip install -r requirements.txt
  python run.py -c config.yml
  ```
- **适用场景**：
  后续解说小子或长文需要批量备份对标博主所有合集、高清切片或挂后台批量采集时，可快速拉取或通过 Docker/REST API 封装为技能。
