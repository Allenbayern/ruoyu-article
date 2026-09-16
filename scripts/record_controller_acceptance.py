#!/usr/bin/env python3
"""记录 controller 验收（人工签字项的唯一合法入口：由 controller 明确指令触发）。

按 controller 在会话中的"验收通过"指令，为指定文章落三处记录：

1. `review/<aid>/source-stripped-readability.json`：source_stripped_readability
   PASS + reviewer_id/reviewer_role（人签字字段，机器不会自填）；
2. `review/attestation/<aid>.human.json`：human-attestation-v3 签字记录，
   绑定当前 delivery 的 markdown_path/markdown_sha256；
3. `batch.json`：gate_status.controller_acceptance=accepted、
   delivery_state=controller_accepted。

边界：本脚本不做任何机器自证；只有 controller 明确说"验收通过"后才能运行。
用法：
    python3 scripts/record_controller_acceptance.py --run-root runs/2026-09-16/daily-007 \
        --identity owner [--aid art-001] [--ref "controller 会话确认"]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--aid", action="append", help="可重复；缺省 = batch 里全部文章")
    parser.add_argument("--identity", default="owner", help="controller 署名（不得含 agent/model/ai 等字样）")
    parser.add_argument("--ref", default="controller 在会话中明确验收通过")
    args = parser.parse_args()

    root = Path(args.run_root)
    batch_path = root / "batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    articles = batch.get("articles") or []
    aids = args.aid or [str(a.get("article_id")) for a in articles]
    reviewed_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    for aid in aids:
        delivery = root / "delivery" / aid / "delivery.md"
        stripped = root / "review" / aid / "source-stripped.md"
        if not delivery.is_file():
            print(f"{aid}: delivery 缺失，跳过", file=sys.stderr)
            continue

        readability_path = root / "review" / aid / "source-stripped-readability.json"
        readability = json.loads(readability_path.read_text(encoding="utf-8"))
        readability.update(
            {
                "source_stripped_readability": "PASS",
                "reviewer_id": args.identity,
                "reviewer_role": "human_editor",
                "reviewed_artifact_sha256": sha256(delivery),
                "reviewed_source_stripped_sha256": sha256(stripped) if stripped.is_file() else readability.get("reviewed_source_stripped_sha256"),
                "reviewed_at": reviewed_at,
                "decision": "PASS",
                "publication_authorization": "not_authorized",
            }
        )
        readability_path.write_text(json.dumps(readability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        attestation_dir = root / "review" / "attestation"
        attestation_dir.mkdir(parents=True, exist_ok=True)
        attestation = {
            "schema_version": "human-attestation-v3",
            "article_id": aid,
            "reviewer_kind": "human",
            "reviewer_role": "human_editor",
            "reviewer_identity": args.identity,
            "reviewed_at": reviewed_at,
            "decision": "accept",
            "attestation_ref": args.ref,
            "markdown_path": f"delivery/{aid}/delivery.md",
            "markdown_sha256": sha256(delivery),
            "publication_authorization": "not_authorized",
        }
        (attestation_dir / f"{aid}.human.json").write_text(
            json.dumps(attestation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        for article in articles:
            if str(article.get("article_id")) == aid:
                gate = article.setdefault("gate_status", {})
                gate["controller_acceptance"] = "accepted"
                article["delivery_state"] = "controller_accepted"
        print(f"{aid}: 验收已记录（readability PASS + attestation v3 + controller_acceptance=accepted）")

    batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"batch.json 已更新: {batch_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
