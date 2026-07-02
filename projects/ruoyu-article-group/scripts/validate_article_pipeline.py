#!/usr/bin/env python3
"""若雨随影文章组验证脚本（第一版）

P0 实现：
- 入口文件健康检查
- 四层状态完整性
- 乱码候选检测
- approved白名单 / final成稿 交叉校验

读取来源：本地 Mac 镜像（handover-hotspot/）
"""
from __future__ import annotations

import re
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

TZ = timezone(timedelta(hours=8))

# 入口文件（本地镜像）
WORKSPACE = Path(__file__).resolve().parents[3]
TOTAL_SPEC = WORKSPACE / "handover-hotspot" / "WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10.md"
FEEDBACK_DIR = WORKSPACE / "handover-hotspot" / "04-QUALITY-FEEDBACK"
OLD_FEEDBACK_DIR = WORKSPACE / "handover-hotspot" / "04-FEEDBACK"  # 已弃用
DIRECTOR_REVIEW_PRIMARY = FEEDBACK_DIR / "director-review-latest.md"
DIRECTOR_REVIEW_LEGACY = FEEDBACK_DIR / "nas-director-model-review-latest.md"
ENTRIES = {
    "directive": FEEDBACK_DIR / "directive-latest.md",
    "feedback": FEEDBACK_DIR / "latest-feedback.md",
    "director_review": DIRECTOR_REVIEW_PRIMARY,
    "approved": FEEDBACK_DIR / "article-approved-latest.md",
}
# note: latest-feedback.md 实际是 symlink → 01-DAILY-RUNS/YYYY-MM-DD/media-intel-aios/latest-feedback.md
REPORT_DIR = WORKSPACE / "projects" / "ruoyu-article-group" / "logs"
OUTPUT_BASE = WORKSPACE / "projects" / "ruoyu-article-group" / "ruoyu-output"
OLD_SPEC = WORKSPACE / "handover-hotspot" / "WORKFLOW-V2-CONTENT-PIPELINE.md"
PROJECT_DIR = WORKSPACE / "projects" / "ruoyu-article-group"
TASK_CARD_TEMPLATE = PROJECT_DIR / "templates" / "article-production-task.md"


def is_today_run(target_date: str) -> bool:
    return target_date == datetime.now(TZ).strftime("%Y-%m-%d")


def normalize_title(title: str) -> str:
    title = re.sub(r'^#+\s*', '', title).strip()
    title = re.sub(r'^\d+[-_、.\s]+', '', title).strip()
    title = re.sub(r'\.(md|html)$', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'[《》“”"\'：:，,。！？!？、\s]+', '', title)
    return title.lower()


def is_article_markdown(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    if path.name.startswith("00-") or path.name.startswith("99-bridge-"):
        return False
    return True


def iter_article_markdown(date_str: str) -> List[Path]:
    files = []
    for bucket in ("final", "draft"):
        out_dir = OUTPUT_BASE / bucket / date_str
        if out_dir.exists():
            files.extend(sorted(p for p in out_dir.glob("*.md") if is_article_markdown(p)))
    return files


def add_result(report: Dict[str, Any], level: str, check: str, detail: str | None = None) -> None:
    report["results"].append({"level": level, "check": check, "detail": detail})
    report["summary"][level] = report["summary"].get(level, 0) + 1


def file_summary(p: Path) -> Dict[str, Any]:
    if p.is_symlink() and not p.exists():
        return {
            "exists": False,
            "size": 0,
            "mtime": None,
            "status": "BROKEN_SYMLINK",
            "target": str(p.resolve(strict=False)),
        }
    if not p.exists():
        return {"exists": False, "size": 0, "mtime": None, "status": "MISSING"}
    st = p.stat()
    mtime = datetime.fromtimestamp(st.st_mtime, tz=TZ)
    return {
        "exists": True,
        "size": st.st_size,
        "mtime": mtime.isoformat(),
        "status": "EMPTY" if st.st_size == 0 else "OK",
    }


def check_entry_freshness(key: str, path: Path, target_date: str) -> List[Dict[str, Any]]:
    issues = []
    if not path.exists() or path.stat().st_size == 0:
        return issues

    text = path.read_text(encoding="utf-8", errors="ignore")
    stat_date = datetime.fromtimestamp(path.stat().st_mtime, tz=TZ).strftime("%Y-%m-%d")
    has_target_date = target_date in text or stat_date == target_date
    if not has_target_date:
        level = "WARN" if is_today_run(target_date) and key != "directive" else "INFO"
        check = f"{key} 入口日期可能过期" if level == "WARN" else f"{key} 入口日期与目标日不一致"
        issues.append({
            "level": level,
            "check": check,
            "detail": f"目标日期={target_date}，文件mtime日期={stat_date}，正文未包含目标日期；历史回放或长期指令文件不按当日产出 WARN 处理",
        })

    if key == "directive":
        legacy_hit = re.search(r'WORKFLOW-V2-CONTENT-PIPELINE|旧 SOP|V2 精简版|2026-06-08', text)
        if legacy_hit and not re.search(r'WORKFLOW-RECAST-CONTENT-AND-VIDEO-2026-06-10|重铸|只作历史兼容参考，不作为正式判断依据', text):
            issues.append({
                "level": "WARN",
                "check": "directive-latest.md 仍是旧 V2 指令",
                "detail": "当前 directive 仍未切到重铸版口径，验证将以 latest-feedback / director-review / approved 为主判断",
            })

    return issues


def build_suggestions(report: Dict[str, Any]) -> List[str]:
    suggestions = []
    for item in report["results"]:
        level = item.get("level")
        if level not in {"WARN", "FAIL"}:
            continue
        check = item.get("check", "")
        detail = item.get("detail", "")
        text = f"{check} {detail}"
        if level == "FAIL":
            suggestions.append(f"先处理 FAIL：{check}。")
        elif "内容质量门" in text:
            suggestions.append("人工二审前补齐核查摘要、正文、评论/舆论信号与今日热度证据。")
        elif "产出任务卡" in text:
            suggestions.append("按 `templates/article-production-task.md` 补齐文章产出任务卡字段。")
        elif "白名单" in text or "不在 approved" in text:
            suggestions.append("若标题为同题改名，在 approved 表或任务卡中补最终标题/别名。")
        elif level == "WARN" and "HTML" in text:
            suggestions.append("成稿交付时同步生成同名 HTML 文件。")
    if not suggestions:
        suggestions.append("暂无阻断项；可进入人工抽检或下一轮产出。")
    return list(dict.fromkeys(suggestions))


def format_markdown_report(report: Dict[str, Any]) -> str:
    lines = [
        f"# 若雨随影文章组验证报告 | {report['date']}",
        "",
        f"来源：{report['source']}",
        f"结论：{report['conclusion']}",
        f"统计：PASS={report['summary'].get('PASS', 0)} / WARN={report['summary'].get('WARN', 0)} / FAIL={report['summary'].get('FAIL', 0)} / INFO={report['summary'].get('INFO', 0)}",
        "",
        "## 四层状态",
    ]
    layers = report.get("four_layers", {})
    lines.extend([
        f"1. 采集：{'PASS' if layers.get('采集') else 'FAIL'}",
        f"2. 候选/评分：{'PASS' if layers.get('候选/评分') else 'FAIL'}",
        f"3. NAS 总监复评：{'PASS' if layers.get('NAS总监复评') else 'FAIL'}",
        f"4. 正式成稿：{'PASS' if layers.get('正式成稿') else 'FAIL'}",
        "",
        "## 建议动作",
    ])
    for suggestion in build_suggestions(report):
        lines.append(f"- {suggestion}")
    lines.extend(["", "## 检查明细"])
    for item in report["results"]:
        detail = f" — {item.get('detail')}" if item.get("detail") else ""
        lines.append(f"- [{item['level']}] {item['check']}{detail}")
    lines.append("")
    return "\n".join(lines)


def check_old_feedback_dir() -> List[Dict[str, Any]]:
    """检查是否仍读取已弃用的 04-FEEDBACK/ 目录"""
    issues = []
    if OLD_FEEDBACK_DIR.exists():
        old_latest = OLD_FEEDBACK_DIR / "latest-feedback.md"
        old_directive = OLD_FEEDBACK_DIR / "directive-latest.md"
        if old_latest.exists() and old_latest.stat().st_size > 0:
            issues.append({
                "level": "WARN",
                "item": "旧入口 04-FEEDBACK/latest-feedback.md 仍存在",
                "detail": "已弃用目录，不应作为正式判断依据"
            })
        if old_directive.exists() and old_directive.stat().st_size > 0:
            issues.append({
                "level": "WARN",
                "item": "旧入口 04-FEEDBACK/directive-latest.md 仍存在",
                "detail": "已弃用目录，不应作为正式判断依据"
            })
    return issues


def check_old_spec_used() -> List[Dict[str, Any]]:
    """检查是否仍引用旧规格"""
    issues = []
    if OLD_SPEC.exists():
        # 快速检查 — 如果是 archive 就不告警
        is_archive = str(OLD_SPEC).find("archive") >= 0
        if not is_archive:
            issues.append({
                "level": "INFO",
                "item": "旧规格文件 WORKFLOW-V2-CONTENT-PIPELINE.md 仍存在",
                "detail": "已降级为历史参考，不应作为日常执行依据"
            })
    return issues


def detect_garbled_title(title: str) -> List[str]:
    """检测疑似乱码标题"""
    issues = []
    if not title or len(title) < 3:
        return issues
    # 常见乱码模式 — 小心不要误伤正常中文字符
    # 法文重音连续出现3+次
    if re.search(r'[èéêëàâäìíîïòóôöùúûü]{3,}', title):
        issues.append(f"疑似法文重音乱码: {title[:60]}")
    # 含literal unicode转义符 \uXXXX
    if re.search(r'\\u[0-9a-fA-F]{4}', title):
        issues.append(f"含unicode转义符: {title[:60]}")
    # 纯数字/hex标题
    if re.search(r'^\d+[）)]\s*$', title) or re.search(r'^[A-F0-9]{16,}$', title):
        issues.append(f"疑似纯数字/hex标题: {title[:60]}")
    return issues


def extract_article_candidates(text: str) -> List[Dict[str, Any]]:
    """从 latest-feedback 中提取文章候选"""
    candidates = []
    in_article = False
    lines = text.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        if re.search(r'文章组', line) or re.search(r'#.*文章组', line):
            in_article = True
            continue
        if re.search(r'视频组', line) or re.search(r'#.*视频组', line):
            in_article = False
            continue
        if in_article:
            # 表格行或候选
            table_match = re.search(r'\|\s*\d+\s*\|\s*(.+?)\s*\|', line)
            if table_match:
                title = table_match.group(1).strip()
                candidates.append({
                    "title": title,
                    "source_line": i + 1,
                    "full_line": line[:200],
                    "garbled": detect_garbled_title(title),
                })
    return candidates


def extract_heading(content: str) -> str | None:
    title_match = re.search(r'^##?\s*(.+)', content, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()
    return None


def extract_approved_titles(approved_text: str) -> List[str]:
    titles = []
    for line in approved_text.split('\n'):
        stripped = line.strip()
        bullet = re.match(r"-\s*\d+\.\s*\[[^\]]+\]\s*(?P<title>.+?)｜", stripped)
        if bullet:
            titles.append(bullet.group("title").strip())
            continue
        if not stripped.startswith('|'):
            continue
        cells = [cell.strip() for cell in stripped.strip('|').split('|')]
        if not cells or re.fullmatch(r'[-:\s]+', cells[0]) or cells[0] in {"题目", "标题", "拍板题目"}:
            continue
        if cells[0]:
            titles.append(cells[0])
    return titles

def title_matches_approved(candidates: List[str], approved_titles: List[str]) -> bool:
    approved_norm = [normalize_title(t) for t in approved_titles if normalize_title(t)]
    candidate_norm = [normalize_title(t) for t in candidates if t and normalize_title(t)]
    for candidate in candidate_norm:
        for approved in approved_norm:
            if candidate == approved or candidate in approved or approved in candidate:
                return True
    return False


def check_article_task_cards(date_str: str) -> List[Dict[str, Any]]:
    issues = []
    if not TASK_CARD_TEMPLATE.exists() or TASK_CARD_TEMPLATE.stat().st_size == 0:
        return [{
            "level": "WARN",
            "item": "文章产出任务卡模板缺失",
            "detail": str(TASK_CARD_TEMPLATE),
        }]

    article_files = iter_article_markdown(date_str)
    if not article_files:
        return [{
            "level": "INFO",
            "item": "未发现当日 draft/final 文章稿",
            "detail": f"检查目录：{OUTPUT_BASE / 'draft' / date_str} 与 {OUTPUT_BASE / 'final' / date_str}",
        }]

    required_markers = {
        "核查摘要": r'核查摘要',
        "正文": r'\n\S.{80,}',
        "今日热度证据": r'今日|当天|热度|排名|评论|讨论|高赞|热搜|榜',
        "评论/舆论信号": r'评论|高赞|热评|弹幕|观众|网友|讨论|争议',
    }
    task_card_markers = {
        "主平台": r'主平台|今日头条|微信公众号|双平台',
        "标题池/备选标题": r'标题池|备选标题|最终标题',
        "二审问题/结论": r'二审|复核|核查摘要|风险素材',
    }

    for article_file in article_files:
        content = article_file.read_text(encoding="utf-8", errors="ignore")
        missing_quality = [label for label, pattern in required_markers.items() if not re.search(pattern, content, re.IGNORECASE)]
        missing_task_card = [label for label, pattern in task_card_markers.items() if not re.search(pattern, content, re.IGNORECASE)]
        if missing_quality:
            issues.append({
                "level": "WARN",
                "item": f"内容质量门缺项: {article_file.name}",
                "detail": f"缺少：{', '.join(missing_quality)}；人工二审前必须补齐正文/评论/今日热度/核查摘要证据",
            })
        if missing_task_card:
            issues.append({
                "level": "WARN",
                "item": f"产出任务卡字段不完整: {article_file.name}",
                "detail": f"缺少：{', '.join(missing_task_card)}；建议按 templates/article-production-task.md 补齐后再二审",
            })

    if not issues:
        issues.append({"level": "PASS", "item": "文章产出任务卡与内容质量门已覆盖", "detail": f"检查稿件数={len(article_files)}"})
    return issues


def check_four_layers(text: str) -> Dict[str, Any]:
    """检查四层状态：采集/候选评分/复评/正式成稿"""
    layers = {
        "采集": False,
        "候选/评分": False,
        "NAS总监复评": False,
        "正式成稿": False,
    }
    # key phrases
    if re.search(r'采集|hunter|猎手|素材', text):
        layers["采集"] = True
    if re.search(r'候选.*评分|candidate|评分.*候选|Top.*候选', text):
        layers["候选/评分"] = True
    if re.search(r'总监复评|二次复评|director.*review|复评包', text):
        layers["NAS总监复评"] = True
    if re.search(r'正式成稿|final|拍板|主推|主稿|可写', text):
        layers["正式成稿"] = True
    return layers


def check_approved_final_consistency(date_str: str) -> List[Dict[str, Any]]:
    """检查 approved 白名单与 final 成稿一致性"""
    issues = []
    approved = FEEDBACK_DIR / "article-approved-latest.md"
    final_dir = OUTPUT_BASE / "final" / date_str
    draft_dir = OUTPUT_BASE / "draft" / date_str

    if not approved.exists() or approved.stat().st_size == 0:
        return [{"level": "WARN", "item": "article-approved-latest.md 为空或不存在", "detail": "今日可能无拍板或白名单未更新"}]

    approved_text = approved.read_text(encoding="utf-8", errors="ignore")
    approved_titles = extract_approved_titles(approved_text)

    # 检查 final 目录：允许正文标题、文件名 slug、approved 标题三路归一匹配，避免脆弱的逐字相等误报。
    if final_dir.exists():
        for md_file in final_dir.glob("*.md"):
            if not is_article_markdown(md_file):
                continue
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            heading = extract_heading(content)
            title_candidates = [md_file.stem]
            if heading:
                title_candidates.append(heading)
            approved_alias = re.search(r'approved 原题[:：]\s*(.+)', content)
            if approved_alias:
                title_candidates.append(approved_alias.group(1).strip())
            if approved_titles and not title_matches_approved(title_candidates, approved_titles):
                issues.append({
                    "level": "FAIL",
                    "item": f"final成稿「{md_file.name}」不在 approved 白名单中",
                    "detail": f"候选标题={title_candidates}；approved 标题未匹配。若为同题改名，请在任务卡/approved 中补最终标题或别名"
                })

    # 检查没有 final 只有 draft
    has_final = final_dir.exists() and any(final_dir.glob("*.md"))
    has_draft = draft_dir.exists() and any(draft_dir.glob("*.md"))
    if has_draft and not has_final:
        issues.append({
            "level": "WARN",
            "item": f"存在 draft（{draft_dir}）但无 final，正式产出状态为「未完成」",
            "detail": "白名单/草稿已生成，但今日文章正式成品目录仍为空"
        })

    return issues


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    today = args.date or datetime.now(TZ).strftime("%Y-%m-%d")

    report = {
        "timestamp": datetime.now(TZ).isoformat(),
        "date": today,
        "source": "[本地镜像]",
        "results": [],
        "summary": {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0},
    }

    # 1. 入口文件健康
    report["entries"] = {}
    for key, path in ENTRIES.items():
        info = file_summary(path)
        report["entries"][key] = info
        if info["status"] == "BROKEN_SYMLINK":
            report["results"].append({"level": "FAIL", "check": f"{key} 入口是断链 symlink", "detail": info.get("target", str(path))})
            report["summary"]["FAIL"] += 1
        elif info["status"] == "MISSING":
            report["results"].append({"level": "FAIL", "check": f"{key} 入口文件缺失", "detail": str(path)})
            report["summary"]["FAIL"] += 1
        elif info["status"] == "EMPTY":
            report["results"].append({"level": "WARN", "check": f"{key} 文件为空", "detail": str(path)})
            report["summary"]["WARN"] += 1
        else:
            report["results"].append({"level": "PASS", "check": f"{key} 入口正常", "detail": f"size={info['size']}bytes, mtime={info['mtime']}"})
            report["summary"]["PASS"] += 1
        for issue in check_entry_freshness(key, path, today):
            report["results"].append(issue)
            report["summary"][issue["level"]] += 1

    # 2. 检查总纲
    spec = file_summary(TOTAL_SPEC)
    if spec["status"] in ("MISSING", "EMPTY"):
        report["results"].append({"level": "FAIL", "check": "总纲文件缺失或为空", "detail": str(TOTAL_SPEC)})
        report["summary"]["FAIL"] += 1
    else:
        report["results"].append({"level": "PASS", "check": "总纲文件存在", "detail": str(TOTAL_SPEC)})
        report["summary"]["PASS"] += 1

    # 3. 旧入口检查
    for issue in check_old_feedback_dir():
        report["results"].append({"level": issue["level"], "check": issue["item"], "detail": issue["detail"]})
        report["summary"][issue["level"]] += 1

    # 4. 旧规格检查
    for issue in check_old_spec_used():
        report["results"].append({"level": issue["level"], "check": issue["item"], "detail": issue["detail"]})
        report["summary"][issue["level"]] += 1

    # 5. 读取 NAS 总监复评
    director_review = DIRECTOR_REVIEW_PRIMARY if DIRECTOR_REVIEW_PRIMARY.exists() else DIRECTOR_REVIEW_LEGACY
    if director_review.exists() and director_review.stat().st_size > 0:
        dr_text = director_review.read_text(encoding="utf-8", errors="ignore")
        # 检查复评是否包含 6 字段
        dr_fields = ["题目", "发布时间", "为什么今天值得写", "写作角度", "风险", "结论"]
        missing_dr = [f for f in dr_fields if f not in dr_text]
        if director_review == DIRECTOR_REVIEW_PRIMARY and re.search(r'文章组候选汇总|视频组候选汇总|总监任务', dr_text) and not re.search(r'为什么今天值得写|写作角度|风险：|结论：', dr_text):
            report["results"].append({
                "level": "WARN",
                "check": "当前复评入口是总编排复评包",
                "detail": "`director-review-latest.md` 已存在，但还不是 6 字段逐条复评格式；当前按有效复评包降级通过，建议后续补结构化字段"
            })
            report["summary"]["WARN"] += 1
        elif missing_dr:
            report["results"].append({
                "level": "FAIL",
                "check": f"NAS 总监复评缺字段: {', '.join(missing_dr)}",
                "detail": "复评必须具备：题目/发布时间/为什么今天值得写/写作角度/风险点/结论"
            })
            report["summary"]["FAIL"] += 1
        else:
            report["results"].append({"level": "PASS", "check": "NAS 总监复评字段完整"})
            report["summary"]["PASS"] += 1

    # 6. 读取 feedback 并分析
    feedback = FEEDBACK_DIR / "latest-feedback.md"
    if feedback.exists() and feedback.stat().st_size > 0:
        text = feedback.read_text(encoding="utf-8", errors="ignore")

        # 四层状态
        layers = check_four_layers(text)
        report["four_layers"] = layers
        missing_layers = [k for k, v in layers.items() if not v]
        if missing_layers:
            report["results"].append({
                "level": "FAIL",
                "check": f"缺少四层状态: {', '.join(missing_layers)}",
                "detail": "文章组必须按采集/候选评分/NAS总监复评/正式成稿汇报"
            })
            report["summary"]["FAIL"] += 1
        else:
            report["results"].append({"level": "PASS", "check": "四层状态完整", "detail": str(layers)})
            report["summary"]["PASS"] += 1

        # 候选质量
        candidates = extract_article_candidates(text)
        report["candidate_count"] = len(candidates)
        garbled = [c for c in candidates if c["garbled"]]
        if garbled:
            for g in garbled:
                report["results"].append({
                    "level": "FAIL",
                    "check": f"疑似乱码候选: {g['title'][:80]}",
                    "detail": "; ".join(g["garbled"]),
                })
                report["summary"]["FAIL"] += 1
        else:
            report["results"].append({"level": "PASS", "check": "未检测到疑似乱码候选"})
            report["summary"]["PASS"] += 1

        # 非影视相关且无母本价值候选
        non_entertainment_keywords = [
            "高考出题人", "粉木耳", "固体饮料", "刷手机", "食品安全", "健康体检",
            "体检中心", "医保", "养老金", "疫苗", "地震", "天气预报"
        ]
        for c in candidates:
            for kw in non_entertainment_keywords:
                if kw in c["title"]:
                    report["results"].append({
                        "level": "WARN",
                        "check": f"疑似非影视相关候选: {c['title'][:80]}",
                        "detail": "含社会/健康/民生关键词，请确认是否仍具备影视相关表达或爆款文章母本价值"
                    })
                    report["summary"]["WARN"] += 1
                    break

        # 检查 "跑了/素材充足" 但无四层拆分
        if re.search(r'跑了|素材.*充足的?', text, re.IGNORECASE) and missing_layers:
            report["results"].append({
                "level": "FAIL",
                "check": "检测到「跑了/素材充足」但无四层状态",
                "detail": "禁止只说「跑了」，必须按四层拆开"
            })
            report["summary"]["FAIL"] += 1

    else:
        report["results"].append({"level": "FAIL", "check": "latest-feedback.md 不存在或为空", "detail": "无法进行深层验证"})
        report["summary"]["FAIL"] += 1

    # 6. approved/final 一致性
    consistency_issues = check_approved_final_consistency(today)
    for ci in consistency_issues:
        report["results"].append({"level": ci["level"], "check": ci["item"], "detail": ci["detail"]})
        report["summary"][ci["level"]] += 1

    # 7. 文章产出任务卡与内容质量门
    task_card_issues = check_article_task_cards(today)
    for issue in task_card_issues:
        report["results"].append({"level": issue["level"], "check": issue["item"], "detail": issue["detail"]})
        report["summary"][issue["level"]] += 1

    # 8. HTML 配套检查
    final_dir = OUTPUT_BASE / "final" / today
    if final_dir.exists():
        md_files = list(final_dir.glob("*.md"))
        for md_file in md_files:
            if md_file.name.startswith("00-") and "补救池" in md_file.name:
                continue
            html_file = md_file.with_suffix(".html")
            if not html_file.exists():
                report["results"].append({
                    "level": "WARN",
                    "check": f"Markdown 成稿无 HTML 配套: {md_file.name}",
                    "detail": "成稿交付后须同步生成排版好的 HTML 版本"
                })
                report["summary"]["WARN"] += 1

    # Final conclusion
    if report["summary"]["FAIL"] > 0:
        report["conclusion"] = "FAIL"
    elif report["summary"]["WARN"] > 0:
        report["conclusion"] = "WARN"
    else:
        report["conclusion"] = "PASS"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{today}-validation.md"
    report_path.write_text(format_markdown_report(report), encoding="utf-8")
    report["report_path"] = str(report_path)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"## 若雨随影文章组验证报告 | {today}")
        print(f"来源: {report['source']}")
        print(f"结论: {report['conclusion']}")
        for r in report["results"]:
            flag = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "INFO": "ℹ️"}.get(r["level"], "•")
            print(f"  {flag} [{r['level']}] {r['check']}")
            if r.get("detail") and r["detail"] != r["check"]:
                print(f"     → {r['detail']}")
        print(f"报告: {report_path}")

    return 0 if report["summary"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
