"""title_freeze: 标题包必须在进 L2 之前冻结，改标题即让旧 approve 失效。

为什么需要（daily-008 复盘）：
该期 art-002 在 L2 判 approve **之后**才做标题级更换，于是多花了一轮增量复核；
而 art-001 的两条 major 修复也牵动了交付哈希。更危险的是引擎的
"completed 记录不回写"守卫加上手工 rebind 脚本（sync_independent_review_008.py）
会把记录里的 title_pack_sha256 直接改成当前文件哈希——**旧 approve 就此被保住**，
哈希绑定形同虚设。

本模块给标题包加一个冻结记录 `review/<aid>/title-freeze.json`：冻结时记下
标题包哈希与选中标题，之后任何一处对不上都判为违规：

- 没有标题包 → `no_title_pack`
- 没有冻结记录 → `not_frozen`
- 标题包哈希与冻结记录不符 → `title_changed_after_freeze`
- L2 记录绑的是另一个冻结版本 → `l2_reviewed_other_freeze`
- 全部一致 → `frozen_ok`

边界：本模块只做证据一致性判定，不写任何发布授权字段。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "title-freeze-v1"
FREEZE_NAME = "title-freeze.json"
BLOCKING_STATUSES = ("no_title_pack", "not_frozen", "title_changed_after_freeze",
                     "l2_reviewed_other_freeze")


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def title_pack_path(run_dir: str | Path, aid: str) -> Path:
    return Path(run_dir) / "review" / aid / "title-pack.json"


def freeze_path(run_dir: str | Path, aid: str) -> Path:
    return Path(run_dir) / "review" / aid / FREEZE_NAME


def selected_title(run_dir: str | Path, aid: str) -> str:
    pack = _load(title_pack_path(run_dir, aid))
    directions = pack.get("directions")
    if isinstance(directions, list) and directions and isinstance(directions[0], Mapping):
        return str(directions[0].get("title") or "")
    return str(pack.get("selected") or pack.get("title") or "")


def freeze(run_dir: str | Path, aid: str, *, note: str = "") -> dict[str, Any]:
    """冻结当前标题包；返回冻结记录（幂等：内容一致则不重写）。"""
    root = Path(run_dir)
    pack = title_pack_path(root, aid)
    digest = _sha256(pack)
    if digest is None:
        return {"status": "no_title_pack", "aid": aid, "reason": f"缺少 {pack.relative_to(root)}"}
    target = freeze_path(root, aid)
    existing = _load(target)
    if existing.get("title_pack_sha256") == digest:
        return {**existing, "status": "already_frozen"}
    record = {
        "schema_version": SCHEMA_VERSION,
        "aid": aid,
        "title_pack_path": str(pack.relative_to(root)),
        "title_pack_sha256": digest,
        "selected_title": selected_title(root, aid),
        "frozen_at": _now(),
        "note": note or "标题包冻结：L2 复核必须绑定本哈希",
        "publication_authorization": "not_authorized",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**record, "status": "frozen"}


def check(run_dir: str | Path, aid: str) -> dict[str, Any]:
    """判定标题包冻结状态，并核对 L2 记录绑定的是否同一个冻结版本。"""
    root = Path(run_dir)
    pack = title_pack_path(root, aid)
    current = _sha256(pack)
    if current is None:
        return {"schema_version": SCHEMA_VERSION, "aid": aid, "status": "no_title_pack",
                "reason": "标题包不存在", "publication_authorization": "not_authorized"}
    record = _load(freeze_path(root, aid))
    frozen_hash = record.get("title_pack_sha256")
    if not frozen_hash:
        return {"schema_version": SCHEMA_VERSION, "aid": aid, "status": "not_frozen",
                "title_pack_sha256": current, "reason": "没有冻结记录，L2 复核前必须先冻结标题包",
                "publication_authorization": "not_authorized"}
    if frozen_hash != current:
        return {
            "schema_version": SCHEMA_VERSION, "aid": aid, "status": "title_changed_after_freeze",
            "title_pack_sha256": current, "frozen_sha256": frozen_hash,
            "frozen_selected_title": record.get("selected_title", ""),
            "current_selected_title": selected_title(root, aid),
            "reason": "标题包在冻结后被改动：旧 L2 approve 失效，需重新复核",
            "publication_authorization": "not_authorized",
        }
    l2 = _load(root / "review" / aid / "codex-l2-review.json")
    l2_hash = l2.get("title_pack_sha256")
    if l2_hash and l2_hash != frozen_hash:
        return {
            "schema_version": SCHEMA_VERSION, "aid": aid, "status": "l2_reviewed_other_freeze",
            "title_pack_sha256": current, "frozen_sha256": frozen_hash, "l2_title_pack_sha256": l2_hash,
            "reason": "L2 复核记录绑定的是另一个标题包版本",
            "publication_authorization": "not_authorized",
        }
    return {
        "schema_version": SCHEMA_VERSION, "aid": aid, "status": "frozen_ok",
        "title_pack_sha256": current,
        "frozen_selected_title": record.get("selected_title", ""),
        "frozen_at": record.get("frozen_at", ""),
        "reason": "标题包已冻结，L2 复核可绑定该哈希",
        "publication_authorization": "not_authorized",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m article_group.title_freeze",
        description="标题包冻结/校验：进 L2 前冻结，改标题即判违规",
    )
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--aid", required=True)
    parser.add_argument("--freeze", action="store_true", help="冻结当前标题包（写入冻结记录）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="冻结状态违规时以非零码退出")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.freeze:
        result = freeze(args.run_root, args.aid)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"{args.aid}: {result['status']} "
                  f"{result.get('title_pack_sha256', '')[:16]} {result.get('selected_title', '')}")
    report = check(args.run_root, args.aid)
    if not args.freeze:
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"{args.aid}: {report['status']} — {report.get('reason', '')}")
    if args.strict and report["status"] in BLOCKING_STATUSES:
        return 1
    return 0


__all__ = [
    "SCHEMA_VERSION",
    "FREEZE_NAME",
    "BLOCKING_STATUSES",
    "title_pack_path",
    "freeze_path",
    "selected_title",
    "freeze",
    "check",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
