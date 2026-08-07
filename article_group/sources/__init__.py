"""article_group.sources — 离线样本解析层（吸收自 media-intel-aios，2026-08-07）。

边界契约
--------
- 本包只做「本地样本 → 结构化 JSON/JSONL」的离线解析。**不发起网络请求**，
  **不读取或注入 cookie/登录态**，**不做事实核验**，**不选择候选**。
- 每个模块保持原 media-intel-aios CLI 契约（`--sample-html`/`--sample-json`/
  `--input` + `--output`），可用 `python -m article_group.sources.<module>` 调用。
- 输出路径由调用方显式给出（受控 run root 由上层编排决定，本包不写任何
  默认产物目录）。
- 解析结果只是候选材料（evidence），不是最终文章质量判断。

模块注册表
----------
| 模块 | 输入 | 输出 |
|---|---|---|
| douban_fetch | 豆瓣影评 HTML | JSON（title/summary/url，og:* 元数据） |
| douban_collect | douban_fetch 输出 | JSONL article 行（article_vault 路由） |
| vocus_fetch | Vocus JSON 样本 | JSON（原样规范化） |
| vocus_collect | vocus_fetch 输出 | JSONL article 行（article_vault 路由） |
| xiniu_collect | 犀牛娱乐 HTML | JSONL 行（title 抽取） |
| hotboard_collect | 热榜 JSON | JSONL dispatch 行（rank/hot_score） |
| zhihu_question_backfill | dispatch JSONL | JSONL queued 行（仅 zhihu.com/question/ URL） |
| route_xiniu_leads | 线索 JSONL | JSONL article 行（默认字段补齐） |

测试：tests/test_sources_parsers.py（全部使用自包含合成样本，不依赖仓库样本文件）。
"""

from __future__ import annotations

PARSERS: dict[str, str] = {
    "douban_fetch": "豆瓣影评 HTML → JSON（og:* 元数据提取）",
    "douban_collect": "豆瓣 fetch 结果 → article_vault JSONL",
    "vocus_fetch": "Vocus JSON 样本 → 规范化 JSON",
    "vocus_collect": "Vocus fetch 结果 → article_vault JSONL",
    "xiniu_collect": "犀牛娱乐 HTML → JSONL（title 抽取）",
    "hotboard_collect": "热榜 JSON → dispatch JSONL",
    "zhihu_question_backfill": "dispatch JSONL → zhihu question 回填队列",
    "route_xiniu_leads": "线索 JSONL → article JSONL（字段补齐）",
}

__all__ = ["PARSERS"]
