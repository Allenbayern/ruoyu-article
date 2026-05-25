# 🔥 热点猎手能力文档

> 创建：2026-05-25 | 用途：供热点猎手（或其他员工）理解现有的热点探测能力

---

## 一、总览

热点猎手采用 **web_fetch (免费) + 本地脚本 (免费) + 浏览器 (需要配对)** 三种方式获取热点信息。每天凌晨自动执行1次。

---

## 二、数据源清单

### ✅ 现用数据源（自动化热榜聚合）

| 平台 | 来源 | 获取方式 | 地址 |
|------|------|----------|------|
| 豆瓣电影 | DailyHotApi | 本地脚本 | `http://192.168.100.223:6688/douban-movie` |
| 知乎热榜 | DailyHotApi | 本地脚本 | `http://192.168.100.223:6688/zhihu` |
| B站热榜 | DailyHotApi | 本地脚本 | `http://192.168.100.223:6688/bilibili` |
| 抖音热榜 | DailyHotApi | 本地脚本 | `http://192.168.100.223:6688/douyin` |
| 虎扑热帖 | DailyHotApi | 本地脚本 | `http://192.168.100.223:6688/hupu` |

- **API 备用端点**：`https://dailyhot.api.lolimi.cn/`、`https://api-hot.imsyy.top/`

### ✅ 搜索引擎（直接 web_fetch）

| 平台 | 搜索URL | 备注 |
|------|---------|------|
| 头条搜索 | `https://so.toutiao.com/search?dvpf=pc&source=input&keyword={话题}` | JS渲染，仅能获取搜索结果片段 |
| 知乎搜索 | `https://www.zhihu.com/search?type=content&q={话题}` | 可获取结果 |
| 百度热搜 | `https://top.baidu.com/board?tab=realtime` | 热榜扫描 |
| 知乎热榜 | `https://www.zhihu.com/hot` | 热榜扫描 |
| 豆瓣电影 | `https://movie.douban.com/` | 新片/热片 |

### ❌ 已停用数据源（Token消耗大，产出低）

| 源 | 停用原因 |
|----|---------|
| thepaper.cn | 零影视相关性产出 |
| TrendAPI | 游戏/动漫为主，影视内容少且质量低 |

---

## 三、配置文件

**路径**：`employees/scripts/dailyhot-config.json`

```json
{
  "sources": {
    "dailyhot": {
      "name": "DailyHot 垂直热榜",
      "base_url": "http://192.168.100.223:6688",
      "script": "employees/scripts/dailyhot-fetch.py",
      "sources": {
        "douban-movie": {"enabled": true},
        "zhihu": {"enabled": true},
        "bilibili": {"enabled": true},
        "douyin": {"enabled": true},
        "hupu": {"enabled": true}
      }
    }
  },
  "filters": {
    "max_fetch": 15,
    "film_include_keywords": [
      "电影","电视剧","综艺","纪录片","动画","动漫","短剧",
      "导演","演员","演技","剧本","编剧","票房","院线","上映",
      "影评","好莱坞","Netflix","漫威","DC",
      "戛纳","奥斯卡","预告片","剧集"
    ],
    "film_exclude_keywords": ["光伏","储能","期货","股票","基金","GitHub","开源"],
    "min_word_count": 200
  }
}
```

**任务定义**：`employees/hotspot-hunter-task.md` — 每次会话加载的完整工作流

---

## 四、脚本工具

存放位置：`employees/scripts/`

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `dailyhot-fetch.py` | 热榜聚合抓取主脚本 | 自动检测API端点，输出JSON+Markdown |
| `dailyhot-run.sh` | 快捷运行脚本 | `./dailyhot-run.sh quick` |
| `article-fetcher.py` | 旧版文章抓取器 | 已弃用 |
| `thepaper-fetch.py` | 澎湃新闻抓取 | 已停用 |
| `trendapi-fetch.py` | TrendAPI抓取 | 已停用 |

### dailyhot-fetch.py 用法

```bash
# 快速模式（4核心源，推荐日常）
./employees/scripts/dailyhot-run.sh quick

# 直接调用
python3 employees/scripts/dailyhot-fetch.py --source douban-movie,weibo,bilibili,douyin --limit 15 --format hotspot-report

# 只抓豆瓣电影
python3 employees/scripts/dailyhot-fetch.py --source douban-movie --format hotspot-report

# 试运行不保存
python3 employees/scripts/dailyhot-fetch.py --dry-run --format hotspot-report
```

---

## 五、标准工作流

```
┌─────────────────────┐
│  热榜扫描（web_fetch） │ ← 百度热搜 / 知乎热榜 / 豆瓣电影
│  或（DailyHot脚本）   │ ← 豆瓣/知乎/B站/抖音/虎扑
└────────┬────────────┘
         ↓
┌─────────────────────┐
│  文章搜索（web_fetch） │ ← 头条搜索/知乎搜索（按话题搜索）
└────────┬────────────┘
         ↓
┌─────────────────────┐
│  全文抓取           │ ← 上限15篇，only S/A级
└────────┬────────────┘
         ↓
┌─────────────────────┐
│  输出《热点简报》    │ ← research-daily/{date}.md
└─────────────────────┘
```

### 工具使用规则

| 工具 | 适用场景 | 限制 |
|------|----------|------|
| `web_fetch` | 热榜扫描、搜索引擎搜索 | 头条文章为JS渲染，无法获取正文 |
| `exec`（脚本） | 运行 dailyhot-fetch.py | 需要网络可达 |
| `browser` | **解决头条文章JS渲染问题** | 需配对后才能使用 |

---

## 六、产出文件

| 文件 | 位置 | 内容 |
|------|------|------|
| 每日研究 | `research-daily/YYYY-MM-DD.md` | 人工阅读的热点简报 |
| 热榜原始数据 | `employees/research-daily/{date}-dailyhot-raw.json` | JSON格式原始热榜数据 |
| 热榜日报 | `employees/research-daily/{date}-dailyhot-report.md` | 可读热榜日报 |
| 管线日志 | `employees/research-daily/{date}-pipeline-log.md` | 完整执行记录 |
| 文章语料 | `employees/article-corpus/{date}/film/` | 抓取的文章正文 |

---

## 七、评分标准

| 等级 | 定义 | 处理方式 |
|------|------|----------|
| 🔴 S级 | 重大事件，全民关注，时效窗口<48h | 立即抓取，出简报 |
| 🟠 A级 | 高热度话题，影视相关，时效窗口48-72h | 抓取，出简报 |
| 🟡 B级 | 日常热点，生命周期短 | **忽略，不抓取** |

---

## 八、已知限制

1. **头条文章JS渲染** — `web_fetch` 无法获取完整正文。计划用 `browser` 工具解决（需先配对），目前仅通过搜索片段判断
2. **DailyHotApi 偶发不可达** — 脚本有自动切换备用端点的逻辑
3. **Token消耗** — 每次完整运行约消耗一次完整上下文，因此限制每天1次
4. **B级热点暂不抓取** — 节约token，只聚焦S/A级

---

## 九、相关文件索引

```
employees/
├── hotspot-hunter.md               # 热点猎手角色定义
├── hotspot-hunter-task.md           # 任务定义（每次加载的工作流）
├── scripts/
│   ├── dailyhot-config.json         # 配置文件
│   ├── dailyhot-fetch.py            # 热榜脚本
│   ├── dailyhot-run.sh              # 快捷脚本
│   └── dailyhot-README.md           # 脚本使用文档
├── research-daily/                  # 产出数据目录
└── article-corpus/                  # 抓取的文章
employees/auto-research/README.md    # 自动研究说明
employees/team-learning.md           # 爆文学习库
```

---

*文档版本：v1.0 | 最后更新：2026-05-25*
