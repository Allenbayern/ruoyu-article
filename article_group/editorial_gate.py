"""编辑质量门禁（2026-09-21 新增；daily-010 两篇成品编读复盘倒推出来的规则）。

为什么需要它：项目里早就有编辑规则（`docs/codex/editorial-learning-playbook.md`
§3「正文先回答读者问题」、§6「开稿最小检查」、§7「获得感写作闸门」、§8「先选形态
再配材料」，以及 `templates/writing-brief.md` 的 opening_scene / judgment_basis /
ending_interaction_question / reference_shape_material_fit），但**没有任何门禁读它们**：
`editorial-protocol` 只校验记录格式合法，`postdraft` 阶段是自述式的，唯一做内容判断
的 `source-stripped-readability` 从 daily-010 到 daily-011 一直是 PENDING。

daily-010 两篇独立编读的结论（两篇互不通气、文章不同、结论一致）：
- 标题问「为什么」/「为什么是这时候」，正文却没有本文自己的因果/判断段——
  art-001 是 14 段里 11 段带归属（「他觉得为什么」），art-002 唯一的解释段是
  「有评论把这一手说得很直白」（匿名外包）；
- art-002 的「标识／授权／专区」三条要求各被复述 4 遍，L17+L35 共 104 字
  （占正文 9.0%）是纯复述；末两节 155 字（13.4%）零新信息；
- art-001 的材料包把来源里的剧情段丢掉了（0 处「剧情」），于是正文按合同
  写不出「这部作品是什么」；art-002 的 5 个来源没有 human_voice，正文零从业者。

边界（与 L2 的分工，别越界）：
- 本门禁只判**读者面结构与承诺兑现**，不重审证据（那是 L2 的活）；
- 机械检查是**报警器**，判决仍归独立编读（`editor_read` 阶段）：默认只记 warning，
  spec 用 ``EDITORIAL_DECLARATIONS`` 逐篇声明要硬拦的项（fail-closed）；
- 通用主题词重复**不做**判定（「复联4」「重映」这类合理重复会被误伤），只查
  spec 逐篇声明的 ``repetition_watch`` 概念。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .content_fidelity import _body_paragraphs
from .independent_review import is_placeholder_record

SCHEMA_VERSION = "editorial-gate-v1"

# 标题里的疑问词：命中才做「可回答性」对账。
TITLE_QUESTION_RE = re.compile(r"为什么|为何|怎么|凭什么")

# 因果/机制表述。只收明确的连接词，不收「就是」「靠的是」这类需要上下文才成立的写法，
# 免得把「A 就是 B」这种定义句当成机制。
CAUSAL_MARKERS = re.compile(
    r"因为|所以|原因是|之所以|这才|正是|意味着|也就是说|问题在于|根本原因|由于|因此"
)

# 归属句起首词：这些段落是「别人说的」，不能当成本文自己的判断段。
ATTRIBUTION_PREFIX_RE = re.compile(
    r"^(?:他|她|他们|对方|会上|发布会|现场|官方|总局|平台|记者|据|有评论|有分析|有观点|有人认为)"
)

# 「作品内容」标记：材料包与正文里判断「这部作品是什么」的线索词。
SUBJECT_CONTENT_MARKERS = re.compile(r"剧情|梗概|类型|题材|主演|角色|改编|又名")

# 复述阈值：一次完整表述 + 最多一次回指。
REPETITION_LIMIT = 2


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _paragraph(paragraphs: list[str], locator: str) -> str:
    match = re.match(r"^p([1-9][0-9]*)", str(locator or ""))
    if not match:
        return ""
    index = int(match.group(1)) - 1
    return paragraphs[index] if 0 <= index < len(paragraphs) else ""


def _causal_paragraphs(paragraphs: list[str]) -> list[str]:
    return [f"p{i}" for i, text in enumerate(paragraphs, start=1) if CAUSAL_MARKERS.search(text)]


def _title_of(title_pack: Mapping[str, Any] | None) -> str:
    if not isinstance(title_pack, Mapping):
        return ""
    selected = str(title_pack.get("selected_title") or "").strip()
    if selected:
        return selected
    directions = title_pack.get("directions")
    if isinstance(directions, list) and directions and isinstance(directions[0], Mapping):
        return str(directions[0].get("title") or "").strip()
    return ""


def build_editorial_gate(
    run_root: str | Path,
    declarations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """按篇判定读者面的结构与承诺兑现，返回门禁报告。

    ``declarations`` 形状（全部可选，缺省=只报警不阻断）::

        {
          "art-001": {
            "strict": True,                # 该篇的 warning 升级为 error
            "own_analysis": True,          # 必须有 own_analysis_locator
            "subject_content": True,       # 必须有 subject_content_locator
            "editor_read": True,           # 必须有 complete 的 editor-review.json
            "repetition_watch": ["标识"],  # 要盯复述的概念
          }
        }
    """

    root = Path(run_root)
    decls: dict[str, Any] = dict(declarations or {})
    errors: list[str] = []
    warnings: list[str] = []
    articles: list[dict[str, Any]] = []

    task_paths = sorted((root / "task-hierarchy").glob("article-task-*.json"))
    if not task_paths:
        errors.append("missing:article_tasks")

    for task_path in task_paths:
        task = _load(task_path) or {}
        aid = str(task.get("article_id") or task_path.stem.replace("article-task-", ""))
        decl = decls.get(aid) if isinstance(decls.get(aid), Mapping) else {}
        strict = bool(decl.get("strict"))

        record = _load(root / f"review/{aid}/content-fidelity.json")
        if record is None:
            errors.append(f"content_fidelity_missing:{aid}")
            articles.append({"article_id": aid, "checks": {}})
            continue

        body = _read_text(root / f"drafts/{aid}/body_draft.md")
        paragraphs = _body_paragraphs(body)
        title = _title_of(_load(root / f"review/{aid}/title-pack.json"))

        def _raise(check: str, message: str) -> None:
            line = f"{check}:{aid}:{message}"
            (errors if strict else warnings).append(line)

        checks: dict[str, Any] = {}

        # 1) 标题可回答性：标题问「为什么」，正文得有本文的因果/机制句。
        if not title:
            checks["title_answerability"] = {"status": "not_applicable", "reason": "title_missing"}
        elif not TITLE_QUESTION_RE.search(title):
            checks["title_answerability"] = {"status": "not_applicable", "title": title}
        else:
            causal = _causal_paragraphs(paragraphs)
            status = "ok" if causal else ("error" if strict else "warning")
            checks["title_answerability"] = {
                "status": status,
                "title": title,
                "causal_paragraphs": causal,
                "mechanism_locator": record.get("mechanism_locator"),
            }
            if not causal:
                _raise(
                    "title_answerability",
                    f"标题含疑问词但正文 0 段因果/机制句（标题：{title}）",
                )

        # 2) 概念复述：只查 spec 逐篇点名的概念。
        concepts = decl.get("repetition_watch") or []
        if isinstance(concepts, (list, tuple)) and concepts:
            counts = {str(c): len(re.findall(re.escape(str(c)), body)) for c in concepts}
            over = {c: n for c, n in counts.items() if n > REPETITION_LIMIT}
            checks["repetition_watch"] = {
                "status": "ok" if not over else ("error" if strict else "warning"),
                "counts": counts,
                "over_limit": over,
            }
            for concept, count in sorted(over.items()):
                _raise("repetition_watch", f"「{concept}」复述 {count} 次（上限 {REPETITION_LIMIT}）")

        # 3) 本文自己的判断段（不能是「他说」）。
        if decl.get("own_analysis"):
            locator = str(record.get("own_analysis_locator") or "").strip()
            text = _paragraph(paragraphs, locator)
            if not locator or not text:
                errors.append(f"own_analysis_locator_missing:{aid}")
                checks["own_analysis"] = {"status": "error", "locator": locator}
            elif ATTRIBUTION_PREFIX_RE.match(text):
                errors.append(f"own_analysis_locator_is_attribution:{aid}:{locator}")
                checks["own_analysis"] = {"status": "error", "locator": locator, "paragraph": text[:60]}
            else:
                checks["own_analysis"] = {"status": "ok", "locator": locator, "paragraph": text[:60]}

        # 4) 作品内容段：让读者知道「这部作品是什么」。
        if decl.get("subject_content"):
            locator = str(record.get("subject_content_locator") or "").strip()
            text = _paragraph(paragraphs, locator)
            if not locator or not text:
                errors.append(f"subject_content_locator_missing:{aid}")
                checks["subject_content"] = {"status": "error", "locator": locator}
            else:
                checks["subject_content"] = {
                    "status": "ok",
                    "locator": locator,
                    "has_content_marker": bool(SUBJECT_CONTENT_MARKERS.search(text)),
                }

        # 5) 编读记录：声明了就必须有结论（占位符不算）。
        if decl.get("editor_read"):
            editor = _load(root / f"review/{aid}/editor-review.json")
            if editor is None:
                errors.append(f"editor_review_missing:{aid}")
                checks["editor_read"] = {"status": "error"}
            elif is_placeholder_record(editor) or str(editor.get("status") or "").lower() != "complete":
                errors.append(f"editor_review_not_complete:{aid}:{editor.get('status')}")
                checks["editor_read"] = {"status": "error", "record_status": editor.get("status")}
            else:
                checks["editor_read"] = {
                    "status": "ok",
                    "decision": editor.get("decision"),
                    "findings": len(editor.get("findings") or []),
                }

        articles.append({"article_id": aid, "checks": checks, "declared": sorted(decl)})

    return {
        "schema_version": SCHEMA_VERSION,
        "pass": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "articles": articles,
        "declarations": decls,
        "note": (
            "读者面结构与承诺兑现的机械判定；默认只报警，spec 用 EDITORIAL_DECLARATIONS "
            "逐篇声明才硬拦。判决（信息增量、判断质量）仍归 editor_read 阶段的独立编读，"
            "本门禁不替代它，也不重审证据（那是 L2 的活）。"
        ),
        "publication_authorization": "not_authorized",
    }
