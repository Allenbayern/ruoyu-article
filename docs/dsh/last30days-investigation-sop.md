# last30days 舆情雷达与钩子探针实操 SOP

> 状态：**provisional**（2026-10-10 实测跑通，接入技能 `~/.agents/skills/last30days-cn`）  
> 适用范围：若雨文章组（`ruoyu-film-daily`）R0 晨间热榜扫描、R1 选题互动量化与 R2 任务卡钩子深挖。

---

## 一、 为什么接入 & 职责边界

### 1. 核心价值
- **R0 跨平台共振感知**：汇总微博、抖音、头条、B站、知乎热榜，自动合并跨平台热点（同一事件多平台同登榜），大幅提升大事件命中率。
- **R1 爆款评分客观化**：带回真实客观的播放、点赞、转评、弹幕数据，解决过去“传播速度/情绪张力”缺乏量化证据的问题。
- **R2 最强钩子与已知锚点深挖**：快速锁定观众真正在争吵与吐槽的点，提炼任务卡 5 大必填字段（尤其是 Truth Gap / 争议缺口）。

### 2. 严格的边界红线
- **禁止在线动态侵入写作与复核**：`last30days` 仅在 R0–R2 在线使用。一旦进入 R3–R8（正文、风格门禁、朱雀检测、L2 复核），必须断网运行，所有证据依赖已保存的静态快照。
- **不可替代长篇正文抓取**：深度拉片与参考长文，仍需使用 `wechat_capture`、`toutiao_capture`、`bilibili_capture` 获取富文本正文。
- **凭据与安全性**：本地无头运行已配置 `LAST30DAYS_DISABLE_BROWSER=1`。严禁将登录 Cookie 或令牌写入 git 仓库或 Vault。

---

## 二、 常用操作命令

### 1. 晨间全网热榜扫描（发现跨平台影视大事件）
```bash
# 扫描全网实时热榜并聚合跨平台热点（微博/百度/抖音/头条/B站/知乎）
python3 scripts/last30days_scout.py --hot

# 过滤特定影视关键词
python3 scripts/last30days_scout.py --hot --topic "电影"
python3 scripts/last30days_scout.py --hot --topic "票房"
```

### 2. 针对候选选题定向深挖（提取争议与钩子）
```bash
# 针对特定作品/事件进行 30 天跨社媒讨论检索（B站/知乎/微博/头条）
python3 scripts/last30days_scout.py \
    --topic "飞天奖 宋佳" \
    --search bili,zhihu,weibo,toutiao \
    --quick

# 深度检索并沉淀到当前批次的 sources/ 证据库
python3 scripts/last30days_scout.py \
    --topic "山花烂漫时 张桂梅" \
    --search bili,zhihu,weibo \
    --deep \
    --out runs/$(date +%F)/daily-015/sources/last30days-research-art-001.md
```

---

## 三、 输出如何回填到文章组契约

### 1. 选题池 `candidate-pool.json`
- `event_cluster_id`：若在 `last30days --hot` 发现同时登上多平台热榜，填入统一事件簇 ID（如 `feitian-35-songjia`）。
- `signal_source`：记录实际命中平台（如 `Weibo#4 + Zhihu#6 + Douyin#12`）。
- `evidence_readiness`：根据返回的数据量与互动数标记 `ready`。

### 2. 任务卡（Task Card）5 大必填字段映射
- **最强钩子（Strongest Truth Gap）**：从知乎/B站高赞争论中提取（例如：“单角色包揽三大奖是角色红利还是绝对演技？”、“视帝爆冷争议”）。
- **读者已知锚点（Known Anchor）**：从热搜榜第一句提取大众耳熟能详的基础事实（例如：“《山花烂漫时》”、“张桂梅”、“白玉兰与金鹰”）。
- **站队点 / 金句（Standpoint）**：观察大众共鸣后提炼出的犀利洞察。
- **事实底座（Facts Foundation）**：从抓取到的官媒与平台快照中提取日期、奖项名称、获奖作品、准确数字。

---

## 四、 平台通路诊断

若怀疑网络或某个平台接口有变动，可随时运行诊断：
```bash
python3 ~/.agents/skills/last30days-cn/scripts/last30days.py --diagnose
```
各平台默认降级策略健全，即使部分平台无登录态，也会自动通过公开搜索兜底，不会阻断流程。
