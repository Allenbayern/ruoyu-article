"""发布前审补充层（advisory）契约测试。

这组测试守的是**边界**，不是"扫得准不准"：

1. 记录里没有 `pass`，且显式声明不构成发布授权（不许被别的模块读成门禁）；
2. **候选永不影响退出码**（含 critical），只有"扫描器坏了"才非零 ——
   这是防"扫描失败被当成干净"的唯一机制；
3. 扫描器坏 / vendor 缺失 / 无稿件，都必须落成显式状态，不许静默变干净；
4. 商业口径未声明时从严 `default_strict`；
5. 摊给复核者的候选一律 `unjudged`，且**不含** `decision` 字段（本层不自任裁判）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import signal
from pathlib import Path

import pytest

from article_group import publish_precheck

CRITICAL_TEXT = "这个项目稳赚不赔，月入十万不是梦，扫码进群领资料。"
CLEAN_TEXT = "他坐在那儿看了很久，什么也没说。"

# 触发 commercial-expression.R03（critical，commercial_only）
COMMERCIAL_TEXT = "我们的课程保证让你的收入翻倍，稳赚不赔，加微信进群领资料。"


@pytest.fixture
def vendor(tmp_path: Path) -> Path:
    """最小 vendor：够 stage_workspace 复制，且默认走真实仓库那份（存在时）。"""
    real = publish_precheck.skill_dir()
    if (real / "scripts" / "scan.py").is_file():
        return real
    pytest.skip("vendor skill 不在仓库内，跳过依赖真实 scan.py 的用例")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 vendor 指向真实仓库、规则目录指向空的临时目录，避免测试耦合我的私有词库。"""
    rules = tmp_path / "rules"
    rules.mkdir()
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(publish_precheck.skill_dir()))
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))
    return rules


def _write_run(tmp_path: Path, body: str, *, article_id: str = "art-001") -> Path:
    root = tmp_path / "daily-900"
    draft = root / "drafts" / article_id
    draft.mkdir(parents=True)
    (draft / "body_draft.md").write_text(body, encoding="utf-8")
    return root


# 非空合法词表：L2-03 之后空词表是一等失败（error），不再是"跑了但没命中"。
VALID_TERMS = json.dumps(
    {
        "terms": [
            {
                "rule": "fake-R01",
                "pattern": "稳赚不赔",
                "severity": "high",
                "doc": "rules-common.md",
                "title": "绝对化收益承诺",
            }
        ]
    },
    ensure_ascii=False,
)


def _fake_skill(
    tmp_path: Path,
    scan_body: str,
    *,
    terms: str = VALID_TERMS,
    name: str = "fake-skill",
    manifest_paths: tuple[str, ...] = ("scripts/scan.py", "scripts/terms.json"),
) -> Path:
    """最小可跑 vendor：scan.py 可定制，terms.json 必须非空合法（否则先撞 L2-03 闸）。

    L2R2-03 之后还必须带 `VENDOR.sha256`：校验**缺席**等于失败，不再是"跳过比对"。
    哈希按写盘字节现算，所以默认 fake 是"清单与词表相符"的诚实形态。

    `manifest_paths` 决定清单里列哪些文件（L2R5-01 之后清单是**逐条**校验的）。
    默认列 `scripts/scan.py` + `scripts/terms.json`（L2R6-01：`REQUIRED_MANIFEST_ENTRIES`
    必须出现在清单上，否则"删掉那一行"就等于"没扫成"却报 `ran`）；要覆盖"清单被裁表"
    这类攻击，显式传更窄的元组。
    """
    fake = tmp_path / name
    (fake / "scripts").mkdir(parents=True)
    (fake / "scripts" / "scan.py").write_text(scan_body, encoding="utf-8")
    (fake / "scripts" / "terms.json").write_text(terms, encoding="utf-8")
    lines = []
    for rel in manifest_paths:
        target = fake / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{rel}")
    (fake / "VENDOR.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return fake


# --------------------------------------------------------------- advisory 边界


def test_record_never_claims_pass_or_publication_authorization(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["layer"] == "advisory"
    assert record["gate_effect"] == "none"
    assert record["blocking"] is False
    assert record["authorizes_publication"] is False
    assert record["publication_authorization"] == "not_authorized"
    # 最关键的一条：没有 pass 字段，"通过"这个词无从被下游读走。
    assert "pass" not in record
    assert record["verdict"] == "advisory_only"


def test_critical_candidate_does_not_touch_gate_or_exit_code(
    tmp_path: Path, env: Path, capsys: pytest.CaptureFixture[str]
):
    root = _write_run(tmp_path, CRITICAL_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "ran"
    assert record["totals"]["candidates"] >= 1
    assert any(c["severity"] == "critical" for c in record["articles"][0]["candidates"])
    # 命中 critical 也照样没有 pass / 照样说 advisory_only
    assert "pass" not in record

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    assert code == 0  # 候选不影响退出码


def test_zero_candidates_is_not_reported_as_safe(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["totals"]["candidates"] == 0
    # 零候选必须伴随"≠安全"的显式说明，而不是任何"clean/ok/pass"字样
    assert "零候选" in record["note"] or "≠安全" in record["note"]
    assert "pass" not in record
    assert "safe" not in json.dumps(record, ensure_ascii=False).lower()


# --------------------------------------------------------------- 失败必须显性


def test_missing_vendor_is_not_run_not_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(tmp_path / "nope"))
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "not_run"
    assert record["reason"].startswith("skill_missing:")
    assert "pass" not in record


def test_missing_vendor_exits_nonzero_and_says_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """扫描器不可用 = 没跑成 → 非零（fail-closed）；但措辞必须说清"不是通过"。"""
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(tmp_path / "nope"))
    root = _write_run(tmp_path, CLEAN_TEXT)

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    err = capsys.readouterr().err
    assert code == 1  # 未知/不可用原因默认非零
    assert "NOT RUN" in err and "不是通过" in err


def test_benign_not_run_exits_zero(tmp_path: Path, env: Path, capsys: pytest.CaptureFixture[str]):
    """确实没什么可扫（无稿件 / 声明关闭）是良性 not_run：退出 0，但仍说"不是通过"。"""
    root = tmp_path / "daily-empty"
    (root / "drafts").mkdir(parents=True)

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    err = capsys.readouterr().err
    assert code == 0
    assert "NOT RUN" in err and "不是通过" in err


def test_rules_dir_missing_is_not_run_not_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2-02：我们的规则目录缺失 → not_run（绝不落成"已扫 + 0 命中"）。"""
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(tmp_path / "no-rules"))
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "not_run"
    assert record["reason"].startswith("rules_missing:")
    assert record["totals"]["scanned"] == 0

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    assert code == 1


def test_empty_rule_library_is_surfaced_not_silent(tmp_path: Path, env: Path):
    """规则目录在但一条规则都没有：可以 ran，但必须显式说明"0 命中是没有规则"。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["rules"]["exists"] is True
    assert record["rules"]["can_match"] is False
    assert record["totals"]["personal_hits"] == 0
    assert "personal_rules_note" in record


def test_terms_table_empty_or_mismatched_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path, capsys: pytest.CaptureFixture[str]
):
    """L2-03：官方词表空 / 与 VENDOR.sha256 不符 → error，不许说"扫过且没命中"。"""
    empty = _fake_skill(
        tmp_path, "import sys; sys.stdout.write('{}')\n", terms=json.dumps({"terms": []})
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(empty))
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"] == "terms_table_empty"
    assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1
    assert "ADVISORY SCAN ERROR" in capsys.readouterr().err

    # 词表非空、但落盘哈希与清单不符 → 同样 error（防"带着未验证哈希显得可复现"）
    tampered = _fake_skill(tmp_path, "import sys; sys.stdout.write('{}')\n", name="tampered")
    (tampered / "VENDOR.sha256").write_text(
        "0" * 64 + "  scripts/terms.json\n", encoding="utf-8"
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(tampered))
    record2 = publish_precheck.build_publish_precheck_advisory(root)
    assert record2["status"] == "error"
    assert record2["articles"][0]["reason"] == "terms_table_hash_mismatch"


def test_broken_scanner_reports_error_and_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path, capsys: pytest.CaptureFixture[str]
):
    """vendor 在、但 scan.py 一跑就炸 —— 必须 error + 非零，绝不落成"干净"。"""
    broken = _fake_skill(tmp_path, "raise SystemExit(3)\n", name="broken-skill")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(broken))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "all_scans_failed"
    assert record["errors"]

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    assert code == 1
    assert "ADVISORY SCAN ERROR" in capsys.readouterr().err


def test_garbage_scanner_output_is_error_not_empty_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """输出不是 JSON 时不许退化成"0 候选"。"""
    fake = _fake_skill(tmp_path, "import sys; sys.stdout.write('not json at all')\n")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "all_scans_failed"  # 顶层只汇总
    # 具体病因在逐篇报告里，不能被汇总层吞掉
    assert record["articles"][0]["reason"].startswith("scan_output_not_json")
    assert record["totals"]["candidates"] == 0
    assert record["totals"]["scanned"] == 0  # 与"扫过且 0 候选"区分开


def test_partial_failure_is_marked_partial(tmp_path: Path, env: Path, monkeypatch: pytest.MonkeyPatch):
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="art-001")
    second = root / "drafts" / "art-002"
    second.mkdir(parents=True)
    (second / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    (second / "body_draft.md").chmod(0o000)
    try:
        record = publish_precheck.build_publish_precheck_advisory(root)
        if record["status"] == "ran":
            pytest.skip("以 root 运行，读权限位不生效")
        assert record["status"] == "partial"
        assert record["totals"]["scanned"] == 1
        assert record["totals"]["failed"] == 1
    finally:
        (second / "body_draft.md").chmod(0o644)


def test_disabled_by_declaration(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(
        root, declaration={"enabled": False}
    )
    assert record["status"] == "not_run"
    assert record["reason"] == "disabled_by_declaration"


# --------------------------------------------------------------- 商业口径从严


def test_commercial_defaults_to_strict_when_undeclared(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["options"]["commercial"] is True
    assert record["options"]["commercial_source"] == "default_strict"


def test_declaration_can_relax_commercial(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(
        root, declaration={"commercial": False}
    )
    assert record["options"]["commercial"] is False
    assert record["options"]["commercial_source"] == "declaration"


def test_cli_flag_overrides_declaration(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root, commercial=False)
    assert record["options"]["commercial"] is False
    assert record["options"]["commercial_source"] == "cli"


def test_commercial_term_is_missed_when_commercial_is_off(tmp_path: Path, env: Path):
    """商业词在非商业口径下不出现 —— 证明这个开关真的在起作用，也说明默认从严的必要。"""
    on = publish_precheck.scan_text(COMMERCIAL_TEXT, commercial=True)
    off = publish_precheck.scan_text(COMMERCIAL_TEXT, commercial=False)
    assert on["status"] == "ran" and off["status"] == "ran"
    assert (on["raw"] or {}).get("candidates")
    assert not (off["raw"] or {}).get("candidates")


def test_industries_flow_through_to_scanner(tmp_path: Path, env: Path):
    result = publish_precheck.scan_text(CLEAN_TEXT, industries=["medical"])
    assert result["status"] == "ran"
    assert "medical" in (result["raw"] or {}).get("industries", [])


# --------------------------------------------------------------- 声明与稿件发现


def test_declaration_selects_articles_explicitly(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)  # drafts/art-001
    elsewhere = root / "custom" / "draft.md"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text(COMMERCIAL_TEXT, encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(
        root, declaration={"articles": {"art-777": "custom/draft.md"}}
    )
    assert [a["article_id"] for a in record["articles"]] == ["art-777"]
    # art-001 被显式声明排除，没有被偷偷扫
    assert record["totals"]["articles"] == 1


def test_unreadable_declaration_is_surfaced(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / publish_precheck.DECLARATION_NAME).write_text("{not json", encoding="utf-8")
    decl = publish_precheck.load_declaration(root)
    assert decl["_unreadable"] is True
    assert decl["_path"] == publish_precheck.DECLARATION_NAME
    assert decl["_reason"].startswith("not_json")
    # L2R3-02：坏声明必须冒泡成顶层 error，不许静默回退成"扫 drafts/ 全量"
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"].startswith("declaration_unreadable:not_json")
    assert record["totals"]["scanned"] == 0
    assert record["articles"] == []
    assert record["errors"] == [record["reason"]]
    # "为什么坏"必须留在记录里（初版标记键不带下划线，被回显白名单吃掉）
    assert record["declaration"]["_path"] == publish_precheck.DECLARATION_NAME
    # 声明坏了不回退成"非商业"，仍从严
    assert record["options"]["commercial_source"] == "default_strict"


def test_selected_title_is_scanned(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CLEAN_TEXT)
    pack = root / "review" / "art-001" / "title-pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text(
        json.dumps(
            {
                "directions": [
                    {"title": "平平无奇的一个标题", "selected": False},
                    {"title": "稳赚不赔！月入十万不是梦", "selected": True},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    record = publish_precheck.build_publish_precheck_advisory(root)
    title = record["articles"][0]["title"]
    assert title["text"] == "稳赚不赔！月入十万不是梦"
    assert title["status"] == "ran"
    assert title["candidates"]  # 标题能命中；G14 标题/正文不一致就靠这条


def test_body_sha256_is_recorded(tmp_path: Path, env: Path):
    import hashlib

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    expected = hashlib.sha256(CLEAN_TEXT.encode("utf-8")).hexdigest()
    assert record["articles"][0]["body_sha256"] == expected


def test_vendor_identity_is_pinned(tmp_path: Path, env: Path):
    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
    vendor = record["vendor"]
    assert vendor["skill_id"] == "yuwen-publish-precheck"
    assert len(vendor["scan_sha256"]) == 64
    assert len(vendor["terms_sha256"]) == 64
    assert len(vendor["commit"]) == 40


# --------------------------------------------------------------- 复核交接


def test_reviewer_candidates_are_unjudged_and_carry_no_decision(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CRITICAL_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    findings = publish_precheck.candidate_findings_for_reviewer(record)

    assert findings
    for finding in findings:
        assert finding["status"] == "unjudged"
        assert finding["requires_semantic_judgment"] is True
        # 本层不许替复核者下判定
        assert "decision" not in finding
        assert "verdict" not in finding
        assert "pass" not in finding


def test_reviewer_candidates_point_at_rule_docs(tmp_path: Path, env: Path):
    root = _write_run(tmp_path, CRITICAL_TEXT)
    findings = publish_precheck.candidate_findings_for_reviewer(
        publish_precheck.build_publish_precheck_advisory(root)
    )
    assert all(f["doc"] for f in findings)  # 复核者要能顺藤摸到规则原文
    assert all(f["rule"] for f in findings)  # 官方来源的 rule 也必须非空


# --------------------------------------------------------------- L2 复核回归


# 正文扫得动、只有标题那一次调用失败 —— L2-01 的场景
SCANNER_BODY_OK_TITLE_FAILS = """
import json, sys
text = sys.argv[sys.argv.index("--text") + 1]
if "TITLE_MARKER" in text:
    sys.stderr.write("boom_title\\n")
    raise SystemExit(4)
json.dump({"characters": len(text), "candidates": [], "personal_hits": [],
           "myth_advisories": [], "warnings": []}, sys.stdout)
"""

MY_RULES_WITH_ENTRY = """# 我的规则库

## 黑名单（有明确词面的，scan 自动盯防）

| 词/正则 | 为什么 | 平台 | 级别 | 判法 |
|---|---|---|---|---|
| 三天瘦十斤 | 无法证实的功效承诺 | 全平台 | 高 | 语境判 |
"""


def _rules_with_entry(tmp_path: Path) -> Path:
    rules = tmp_path / "my-rules-dir"
    rules.mkdir()
    (rules / "my-rules.md").write_text(MY_RULES_WITH_ENTRY, encoding="utf-8")
    return rules


def test_title_scan_failure_is_partial_not_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path, capsys: pytest.CaptureFixture[str]
):
    """L2-01（blocker）：标题扫失败必须在 run 级显形，不许报 ran / failed=0。"""
    fake = _fake_skill(tmp_path, SCANNER_BODY_OK_TITLE_FAILS)
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    root = _write_run(tmp_path, CLEAN_TEXT)
    pack = root / "review" / "art-001" / "title-pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text(
        json.dumps(
            {"directions": [{"title": "TITLE_MARKER 的标题", "selected": True}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "partial"
    assert record["totals"]["scanned"] == 0  # 标题没扫完 → 不算"已扫"
    assert record["totals"]["failed"] == 1
    assert record["totals"]["title_failed"] == 1
    assert any("title_scan_error" in e for e in record["errors"])
    assert record["articles"][0]["title"]["status"] == "error"

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    err = capsys.readouterr().err
    assert code == 1  # L2-05：未扫全必须非零
    assert "ADVISORY PARTIAL" in err and "不是通过" in err


def test_declared_article_id_cannot_escape_run_root(
    tmp_path: Path, env: Path, monkeypatch: pytest.MonkeyPatch
):
    """L2-04：id / 路径越界必须显式 error，且绝不在 run 外落任何文件。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    written: list[str] = []

    def _record(path: str, payload: object) -> None:
        written.append(path)

    record = publish_precheck.build_publish_precheck_advisory(
        root,
        write_article_reports=_record,
        declaration={
            "articles": {
                "../../../../outside-art": "drafts/art-001/body_draft.md",
                "art-escape": "../../../../etc/hostname",
                "art-abs": "/etc/hostname",
                "art-ok": "drafts/art-001/body_draft.md",
            }
        },
    )
    by_id = {a["article_id"]: a for a in record["articles"]}
    assert by_id["../../../../outside-art"]["reason"].startswith("invalid_article_id")
    assert by_id["art-escape"]["reason"].startswith("path_escape")
    assert by_id["art-abs"]["reason"].startswith("path_escape")
    assert by_id["art-ok"]["status"] == "ran"
    assert record["status"] == "partial"  # 有篇目失败就必须 partial
    # 写路径只能是 run 内相对路径；越界 id 不产生任何写请求
    # （id 合法但**稿件路径**越界的，报告落在 run 内该 id 名下，记录的是失败本身）
    assert sorted(written) == [
        "review/art-abs/publish-precheck.json",
        "review/art-escape/publish-precheck.json",
        "review/art-ok/publish-precheck.json",
    ]
    assert all(".." not in path for path in written)
    assert not list(tmp_path.glob("outside-art"))
    assert not (tmp_path / "etc").exists()


def test_my_rules_hits_carry_rule_and_doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path):
    """L2-06：自有规则命中也要带 rule/doc，复核者才能摸到规则原文。"""
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))
    root = _write_run(tmp_path, "他三天瘦十斤，什么也没说。")
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "ran"
    hits = record["articles"][0]["personal_hits"]
    assert hits, f"自有规则未命中：{record['articles'][0]}"
    findings = publish_precheck.candidate_findings_for_reviewer(record)
    mine = [f for f in findings if f["source"] == "my-rules"]
    assert mine
    for finding in mine:
        assert finding["rule"]  # 非空
        assert finding["doc"] == "my-rules.md"
        assert finding["title"]  # 就是规则表里的"为什么"
        assert finding["status"] == "unjudged"
        assert "decision" not in finding


def test_rules_identity_is_recorded_and_sensitive_to_edits(tmp_path: Path, env: Path):
    """L2-08：我们自己的规则表也要有哈希，事后能回答"命中的是哪一版"。"""
    rules = _rules_with_entry(tmp_path)
    before = publish_precheck.rules_identity(rules)
    assert before["exists"] is True
    assert len(before["sha256"]) == 64
    assert before["blacklist_rows"] == 1
    assert before["can_match"] is True

    rules2 = tmp_path / "other-rules"
    rules2.mkdir()
    (rules2 / "my-rules.md").write_text(MY_RULES_WITH_ENTRY + "\n| 包治百病 | 功效 | 全 | 高 | 语境判 |\n", encoding="utf-8")
    after = publish_precheck.rules_identity(rules2)
    assert after["sha256"] != before["sha256"]

    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
    assert len(record["rules"]["sha256"]) == 64


def test_declaration_unknown_keys_are_not_echoed(tmp_path: Path, env: Path):
    """L2-07：声明里伪造的 pass 不许被回显进产物。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(
        root, declaration={"enabled": True, "pass": True, "commercial": False}
    )
    assert record["declaration"] == {"enabled": True, "commercial": False}
    assert record["declaration_ignored_keys"] == ["pass"]
    assert "pass" not in record
    assert '"pass":' not in json.dumps(record, ensure_ascii=False)  # 没有名为 pass 的字段


def test_dot_directories_under_drafts_are_not_scanned(tmp_path: Path, env: Path):
    """L2-10：drafts/.before 这类备份不能被当正式稿。"""
    root = _write_run(tmp_path, COMMERCIAL_TEXT)
    backup = root / "drafts" / ".before" / "art-001"
    backup.mkdir(parents=True)
    (backup / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert [a["article_id"] for a in record["articles"]] == ["art-001"]
    assert record["totals"]["candidates"] >= 1  # 扫到的是正式稿（含商业词）


def test_missing_file_argument_is_structured_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """L2-11：单文件模式读不到稿件也要落结构化状态，不要裸回溯。"""
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, "pass\n")))
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))

    code = publish_precheck.main(["--file", str(tmp_path / "nope.md"), "--json"])
    out = capsys.readouterr().out
    record = json.loads(out)
    assert code == 1
    assert record["status"] == "not_run"
    assert record["reason"].startswith("body_unreadable:")
    assert "Traceback" not in out


def test_article_write_failure_keeps_batch_results(tmp_path: Path, env: Path):
    """L2-12：单篇写失败不许让整批结果从汇总里消失。"""
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="art-001")
    second = root / "drafts" / "art-002"
    second.mkdir(parents=True)
    (second / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")

    def _write(path: str, payload: object) -> None:
        if "art-002" in path:
            raise OSError("disk full")

    record = publish_precheck.build_publish_precheck_advisory(root, write_article_reports=_write)
    assert record["status"] == "ran"  # 扫描本身没失败
    assert record["totals"]["articles"] == 2
    assert {a["article_id"] for a in record["articles"]} == {"art-001", "art-002"}
    assert record["write_failures"] == ["art-002"]
    assert any("write_failed" in e for e in record["errors"])


def test_daily_engine_run_record_carries_advisory_status(tmp_path: Path):
    """L2-09：补充层长期 error/not_run 必须在 RUN-RECORD 的独立栏里看得见。"""
    from scripts import daily_engine as engine

    gates = tmp_path / "review" / "gates"
    gates.mkdir(parents=True)
    record = gates / "publish-precheck-advisory.json"

    # 记录缺失 → not_run（不是静默省略这一栏）
    assert engine.publish_precheck_advisory_status(tmp_path) == ("not_run", "")

    record.write_text(
        json.dumps({"status": "error", "reason": "rules_missing:x"}), encoding="utf-8"
    )
    assert engine.publish_precheck_advisory_status(tmp_path) == ("error", "rules_missing:x")

    record.write_text(json.dumps({"status": "partial", "reason": "some_scans_failed"}), encoding="utf-8")
    assert engine.publish_precheck_advisory_status(tmp_path) == ("partial", "some_scans_failed")

    # ran 不带原因；状态词与 pass/fail 不混
    record.write_text(json.dumps({"status": "ran", "reason": ""}), encoding="utf-8")
    assert engine.publish_precheck_advisory_status(tmp_path) == ("ran", "")

    # 记录**存在但读坏**（截断 JSON / 非 UTF-8）→ error 带病因，不许与"根本没跑"同形
    record.write_text("{not json", encoding="utf-8")
    assert engine.publish_precheck_advisory_status(tmp_path) == ("error", "record_not_json")

    record.write_bytes(b'{"status": "ran"}'.replace(b"ran", b"\xff\xfe"))
    assert engine.publish_precheck_advisory_status(tmp_path) == ("error", "record_not_utf8")


# ------------------------------------------------- pilot 版式（2026-10 现行）


def _write_pilot_run(tmp_path: Path, body: str, *, case_id: str | None = "case-900") -> Path:
    """pilot 版式：正文在 run 根 draft.md，没有 drafts/<aid>/。"""
    root = tmp_path / "dsh-pilot-case-900"
    root.mkdir(parents=True, exist_ok=True)
    (root / "draft.md").write_text(body, encoding="utf-8")
    if case_id is not None:
        (root / "pilot-manifest.json").write_text(
            json.dumps({"case_id": case_id, "run_id": root.name}), encoding="utf-8"
        )
    return root


def test_pilot_run_root_draft_is_scanned(tmp_path: Path, env: Path):
    """2026-10 现行 run 全是这一版式；少了兜底，补充层永远不会开火。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "ran"
    assert record["totals"]["articles"] == 1
    assert record["articles"][0]["article_id"] == "case-900"
    assert record["articles"][0]["body_sha256"]  # 可复现性不能因为换版式就丢


def test_pilot_id_falls_back_to_run_dir_name_without_manifest(tmp_path: Path, env: Path):
    """没有 manifest 时用 run 目录名，且必须过 safe_article_id（它会被拼进写路径）。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT, case_id=None)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["articles"][0]["article_id"] == "dsh-pilot-case-900"


def test_pilot_selected_title_is_scanned(tmp_path: Path, env: Path):
    """pilot 标题包是 run 根 title-pack.json + `selected_title` 字符串（无 directions[]）。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT)
    (root / "title-pack.json").write_text(
        json.dumps({"selected_title": "稳赚不赔！月入十万不是梦"}, ensure_ascii=False),
        encoding="utf-8",
    )
    record = publish_precheck.build_publish_precheck_advisory(root)

    title = record["articles"][0]["title"]
    assert title["status"] == "ran"
    assert title["text"] == "稳赚不赔！月入十万不是梦"
    assert title["candidates"]


def test_drafts_layout_wins_over_root_draft(tmp_path: Path, env: Path):
    """两种版式并存时以 drafts/ 为准，绝不把同一篇扫两遍。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "draft.md").write_text("稳赚不赔的投资课", encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["totals"]["articles"] == 1
    assert record["articles"][0]["article_id"] == "art-001"


def test_neither_layout_is_benign_not_run(tmp_path: Path, env: Path, capsys: pytest.CaptureFixture[str]):
    """两种版式都没有 → 良性 not_run（退出 0 但明说"不是通过"），不是"0 候选=干净"。"""
    root = tmp_path / "empty-run"
    root.mkdir()

    assert publish_precheck.main(["--run-root", str(root)]) == 0
    assert "不是通过" in capsys.readouterr().err


# --------------------------------------------------------------------------- L2R2（第 2 轮）

def test_non_utf8_body_is_structured_error_not_traceback(
    tmp_path: Path, env: Path, capsys: pytest.CaptureFixture[str]
):
    """L2R2-01：非 UTF-8 正文原先裸抛 UnicodeDecodeError，CLI 只吐回溯且 stdout 为空。"""
    root = tmp_path / "daily-901"
    draft = root / "drafts" / "art-001"
    draft.mkdir(parents=True)
    (draft / "body_draft.md").write_bytes(b"\xff\xfe\x00\x01 not utf8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"].startswith("body_not_utf8:")

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    captured = capsys.readouterr()
    assert code == 1
    assert "ADVISORY SCAN ERROR" in captured.err
    assert "Traceback" not in captured.err
    assert json.loads(captured.out)["status"] == "error"


def test_non_utf8_declaration_does_not_crash_build(tmp_path: Path, env: Path):
    """L2R2-01 + L2R3-02：声明非 UTF-8 原先在 build 里裸崩，且坏声明不许静默回退成全量扫描。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / publish_precheck.DECLARATION_NAME).write_bytes(b"\xff\xfe{}")

    decl = publish_precheck.load_declaration(root)
    assert decl["_unreadable"] is True
    assert decl["_reason"].startswith("not_utf8:")
    # 声明坏了不回退成"非商业"，仍从严，且不许崩
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"].startswith("declaration_unreadable:not_utf8:")
    assert record["totals"]["scanned"] == 0
    assert record["options"]["commercial_source"] == "default_strict"


def test_non_utf8_title_pack_does_not_crash_build(tmp_path: Path, env: Path):
    """L2R2-01 + L2R3-03：标题包非 UTF-8 原先抛未捕获 UnicodeDecodeError。

    现在不仅不许崩，还必须把"标题从没被扫过"显形 —— 初版报 ran / title=null /
    title_failed=0，与"根本没有标题包"逐字段同形。
    """
    root = _write_run(tmp_path, CLEAN_TEXT)
    pack = root / "review" / "art-001" / "title-pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_bytes(b"\xff\xfe not utf8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert record["status"] == "partial"
    assert record["totals"]["title_failed"] == 1
    assert article["title_failed"] is True
    assert article["reason"].startswith("title_pack_not_utf8:")
    assert article["title"]["status"] == "error"


def test_non_utf8_terms_table_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path):
    """L2R2-01：官方词表非 UTF-8 → 结构化 error，不抛。"""
    fake = _fake_skill(tmp_path, "import sys; sys.stdout.write('{}')\n", name="utf8-terms")
    (fake / "scripts" / "terms.json").write_bytes(b"\xff\xfe{}")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"].startswith("terms_table_not_utf8")


def test_missing_vendor_manifest_is_error_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R2-03：清单缺失/无 terms.json 行时，初版**静默跳过**比对 —— 校验缺席＝失败。"""
    no_manifest = _fake_skill(tmp_path, "import sys; sys.stdout.write('{}')\n", name="no-manifest")
    (no_manifest / "VENDOR.sha256").unlink()
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(no_manifest))
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"] == "vendor_manifest_missing"

    # 清单在、但里面没有 terms.json 那一行：实测把词表缩成 1 条也照样 ran → 必须 error
    no_entry = _fake_skill(
        tmp_path, "import sys; sys.stdout.write('{}')\n", name="no-entry",
        terms=json.dumps({"terms": [{"rule": "x", "pattern": "y"}]}),
    )
    (no_entry / "VENDOR.sha256").write_text("0" * 64 + "  scripts/scan.py\n", encoding="utf-8")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(no_entry))
    record2 = publish_precheck.build_publish_precheck_advisory(root)
    assert record2["status"] == "error"
    assert record2["articles"][0]["reason"] == "vendor_manifest_lacks_terms_entry"


def test_nested_wordlist_is_extra_not_scannable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R2-02：词库放进 wordlists/sub/ 时扫描器根本不加载 —— 不许报 can_match=True。"""
    rules = tmp_path / "nested-rules"
    (rules / "wordlists" / "sub").mkdir(parents=True)
    (rules / "my-rules.md").write_text("# 我的规则库\n", encoding="utf-8")
    (rules / "wordlists" / "sub" / "深词库.md").write_text("稳赚不赔|高风险\n", encoding="utf-8")
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))

    info = publish_precheck.rules_identity(rules)
    assert info["can_match"] is False
    assert info["wordlist_files"] == 0
    assert info["wordlist_terms"] == 0
    assert "wordlists/sub/深词库.md" in info["extra_files"]

    root = _write_run(tmp_path, "他稳赚不赔地走开了。")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "ran"
    assert record["totals"]["personal_hits"] == 0
    # 必须明说"没有规则"，而不是让 0 命中冒充"规则放行"
    assert "personal_rules_note" in record


def test_top_level_txt_wordlist_is_loaded_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R2-02 反向：顶层 .txt 词库扫描器**确实**加载，不许再附"恒为 0"的说明。"""
    rules = tmp_path / "txt-rules"
    (rules / "wordlists").mkdir(parents=True)
    (rules / "my-rules.md").write_text("# 我的规则库\n", encoding="utf-8")
    (rules / "wordlists" / "我的话术.txt").write_text("稳赚不赔|高风险话术\n", encoding="utf-8")
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))

    info = publish_precheck.rules_identity(rules)
    assert info["can_match"] is True
    assert info["wordlist_files"] == 1
    assert info["wordlist_terms"] == 1
    assert info["extra_files"] == []

    root = _write_run(tmp_path, "这个项目稳赚不赔，月入十万。")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "ran"
    assert record["totals"]["personal_hits"] >= 1
    assert "personal_rules_note" not in record


def _write_advisory_record(root: Path, payload: str) -> None:
    target = root / "review" / "gates"
    target.mkdir(parents=True, exist_ok=True)
    (target / "publish-precheck-advisory.json").write_text(payload, encoding="utf-8")


@pytest.mark.parametrize("payload", ["[]", "null", "123", '"x"'])
def test_daily_engine_tolerates_non_object_advisory_record(tmp_path: Path, payload: str):
    """L2R2-04：合法但非对象的 JSON 原先抛 AttributeError，击穿 RUN-RECORD 组装。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    _write_advisory_record(root, payload)
    status, reason = engine.publish_precheck_advisory_status(root)
    assert status == "error"
    assert reason.startswith("record_not_a_mapping:")


def test_daily_engine_rejects_forged_pass_status(tmp_path: Path):
    """L2R2-04：手写 {"status":"pass"} 原先被原样回填进 RUN-RECORD 的独立栏。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    _write_advisory_record(root, json.dumps({"status": "pass"}))
    status, reason = engine.publish_precheck_advisory_status(root)
    assert status == "error"
    assert reason == "unknown_status:pass"
    assert "pass" not in status

    _write_advisory_record(root, json.dumps({"status": "ran"}))
    assert engine.publish_precheck_advisory_status(root) == ("ran", "")
    _write_advisory_record(root, json.dumps({"status": "partial", "reason": "some_scans_failed"}))
    assert engine.publish_precheck_advisory_status(root) == ("partial", "some_scans_failed")


def test_declared_articles_wrong_type_is_visible_not_silently_widened(tmp_path: Path, env: Path):
    """L2R2-05：articles 类型写错原先被静默忽略并回退成全量扫描（无提示）。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    decl_path = root / publish_precheck.DECLARATION_NAME

    decl_path.write_text(json.dumps({"articles": ["art-001"]}), encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"] == "declaration_articles_not_a_mapping:list"
    assert record["totals"]["scanned"] == 0

    decl_path.write_text(json.dumps({"articles": {}}), encoding="utf-8")
    record2 = publish_precheck.build_publish_precheck_advisory(root)
    assert record2["status"] == "error"
    assert record2["articles"][0]["reason"] == "declaration_articles_empty"


def test_declaration_articles_null_does_not_widen_scope(tmp_path: Path, env: Path):
    """L2R11-01：`{"articles": null}` 原先被读成"没声明"→ 静默回退扫 drafts/ 全量。

    声明本该**收窄**范围，结果悄悄放大且 `errors=[]` —— 与"根本没声明"逐字段同形。
    """
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="ok-001")
    (root / "drafts" / "beta-002").mkdir(parents=True)
    (root / "drafts" / "beta-002" / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    decl_path = root / publish_precheck.DECLARATION_NAME

    # 对照：合法收窄声明只扫 1 篇
    decl_path.write_text(
        json.dumps({"articles": {"ok-001": "drafts/ok-001/body_draft.md"}}), encoding="utf-8"
    )
    narrowed = publish_precheck.build_publish_precheck_advisory(root)
    assert narrowed["status"] == "ran"
    assert narrowed["totals"]["scanned"] == 1

    # 无声明：drafts 版式全扫 2 篇（这是合法的另一条路径，不受本次修复影响）
    decl_path.unlink()
    undeclared = publish_precheck.build_publish_precheck_advisory(root)
    assert undeclared["status"] == "ran"
    assert undeclared["totals"]["scanned"] == 2

    # 显式 null：必须 error + 0 篇，**不许**变成"没声明"
    decl_path.write_text(json.dumps({"articles": None}), encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["totals"]["scanned"] == 0
    assert record["articles"][0]["reason"] == "declaration_articles_not_a_mapping:NoneType"
    assert publish_precheck.main(["--run-root", str(root)]) == 1


def test_cli_write_on_sealed_run_is_structured_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path, capsys: pytest.CaptureFixture[str]
):
    """L2R2-06：封存 run 上 CLI --write 原先裸抛 RunSealedError。"""
    from article_group import evidence_write

    root = _write_run(tmp_path, CLEAN_TEXT)

    def _sealed(*_args: object, **_kwargs: object) -> None:
        raise evidence_write.RunSealedError(str(root))

    monkeypatch.setattr(publish_precheck, "_write_record", _sealed)
    code = publish_precheck.main(["--run-root", str(root), "--write"])
    captured = capsys.readouterr()
    assert code == 1
    assert "ADVISORY WRITE FAILED" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------- L2R3（第 3 轮）

MY_RULES_INVALID = """# 我的规则库

## 黑名单（有明确词面的，scan 自动盯防）

| 词/正则 | 为什么 | 平台 | 级别 | 判法 |
|---|---|---|---|---|
| [ | 语法错 | 全平台 | 高 | 语境判 |
"""

MY_RULES_FAKE_CERT = """# 我的规则库

## 黑名单（有明确词面的，scan 自动盯防）

| 词/正则 | 为什么 | 平台 | 级别 | 判法 |
|---|---|---|---|---|
| 假证 | 不可验证的资质承诺 | 全平台 | 高 | 语境判 |
"""


def test_invalid_regex_blacklist_row_is_not_counted_as_loaded(tmp_path: Path, env: Path):
    """L2R3-01：非法正则的行上游 `re.compile` 失败会跳过，本层不许报 can_match=True。

    初版只数行数不编译，于是"一条规则都没装载"被记成"有可匹配规则"（=规则放行）。
    """
    (env / "my-rules.md").write_text(MY_RULES_INVALID, encoding="utf-8")
    root = _write_run(tmp_path, CLEAN_TEXT)

    record = publish_precheck.build_publish_precheck_advisory(root)
    rules = record["rules"]
    assert rules["blacklist_rows"] == 0
    assert rules["blacklist_invalid_rows"] == 1
    assert rules["can_match"] is False
    assert record["status"] == "ran"  # 规则库空是合法起步状态，不改状态
    assert "正则非法" in record["personal_rules_note"]
    assert "没有规则" in record["personal_rules_note"]

    # 对照：同一格的合法词条 → 装载成功、note 消失
    (env / "my-rules.md").write_text(MY_RULES_FAKE_CERT, encoding="utf-8")
    ok = publish_precheck.build_publish_precheck_advisory(root)
    assert ok["rules"]["blacklist_rows"] == 1
    assert ok["rules"]["blacklist_invalid_rows"] == 0
    assert ok["rules"]["can_match"] is True
    assert "personal_rules_note" not in ok


def _write_two_article_run(tmp_path: Path) -> Path:
    root = tmp_path / "daily-902"
    for aid in ("art-001", "art-002"):
        draft = root / "drafts" / aid
        draft.mkdir(parents=True)
        (draft / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    return root


@pytest.mark.parametrize("payload", ["[]", '"x"', "{oops"])
def test_corrupt_declaration_does_not_widen_scope(tmp_path: Path, env: Path, payload: str):
    """L2R3-02：坏声明原先被当"没声明"，静默回退成扫 drafts/ 全量 —— 范围反被放大。"""
    root = _write_two_article_run(tmp_path)
    # 对照：合法声明是**收窄**范围（只扫 1 篇）
    (root / publish_precheck.DECLARATION_NAME).write_text(
        json.dumps({"articles": {"art-002": "drafts/art-002/body_draft.md"}}), encoding="utf-8"
    )
    narrowed = publish_precheck.build_publish_precheck_advisory(root)
    assert narrowed["status"] == "ran"
    assert narrowed["totals"]["scanned"] == 1

    (root / publish_precheck.DECLARATION_NAME).write_text(payload, encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"].startswith(("declaration_unreadable:", "declaration_invalid:"))
    assert record["totals"]["scanned"] == 0  # 不再出现"坏声明 → scanned=2"的全量回退
    assert record["articles"] == []


@pytest.mark.parametrize("payload", ["{oops", "[]"])
def test_corrupt_title_pack_is_partial_not_ran(tmp_path: Path, env: Path, payload: str):
    """L2R3-03：坏标题包不许与"没有标题包"逐字段同形（丢的是 G14 那条唯一检查面）。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    pack = root / "review" / "art-001" / "title-pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text(payload, encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "partial"
    assert record["totals"]["title_failed"] == 1
    assert record["articles"][0]["reason"].startswith("title_pack_")


def test_absent_title_pack_is_still_ran(tmp_path: Path, env: Path):
    """对照：真没有标题包才是 ran + title=null（不许把"没有"也报成失败）。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "ran"
    assert record["totals"]["title_failed"] == 0
    assert record["articles"][0]["title"] is None


def test_title_my_rules_hit_reaches_the_reviewer_list(tmp_path: Path, env: Path):
    """标题上的**自有规则**命中不许消失：标题面本就只剩这一条检查路径。

    L2R10-07：drafts 版式的标题包在 `review/<id>/title-pack.json`（run 根那份只属于
    pilot 单篇 run）—— 本用例原先写在 run 根，修完后必须按本品式放。
    """
    (env / "my-rules.md").write_text(MY_RULES_FAKE_CERT, encoding="utf-8")
    root = _write_run(tmp_path, CLEAN_TEXT)
    pack = root / "review" / "art-001" / "title-pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text(
        json.dumps({"selected_title": "代办假证"}, ensure_ascii=False), encoding="utf-8"
    )

    record = publish_precheck.build_publish_precheck_advisory(root)
    hits = record["articles"][0]["title"]["personal_hits"]
    assert [h["match"] for h in hits] == ["假证"]

    findings = publish_precheck.candidate_findings_for_reviewer(record)
    title_items = [f for f in findings if f["surface"] == "title" and f["source"] == "my-rules"]
    assert title_items and title_items[0]["rule"] == "my-rules:假证"
    assert all(f["status"] == "unjudged" for f in findings)


def test_corrupt_pilot_manifest_leaves_a_trace(tmp_path: Path, env: Path):
    """L2R3-04 / 残留 1：坏 manifest 原先完全无痕，与"没有 manifest"不可分辨。

    而且 id 决定逐篇证据落到 `review/<id>/` —— "扫了但证明不了是哪一篇"必须降级，不许报 ran。
    """
    root = _write_pilot_run(tmp_path, CLEAN_TEXT, case_id=None)
    (root / "pilot-manifest.json").write_bytes(b"\xff\xfe{}")

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert article["article_id_note"] == "run_dir_name"
    assert article["reason"] == "id_unverified:pilot-manifest.json_not_utf8:pilot-manifest.json"
    assert article["status"] == "partial"
    assert record["status"] == "partial"
    assert record["totals"]["scanned"] == 0
    assert any("id_unverified" in e for e in record["errors"])

    # 对照：真没有 manifest → 同样是猜出来的 id，但没有任何"读取失败"的据，照常 ran
    (root / "pilot-manifest.json").unlink()
    clean = publish_precheck.build_publish_precheck_advisory(root)
    assert clean["status"] == "ran"
    assert clean["articles"][0]["article_id_note"] == "run_dir_name"
    assert "id_unverified" not in clean["articles"][0]["reason"]


def test_body_sha256_is_file_bytes(tmp_path: Path, env: Path):
    """L2R3-05：body_sha256 要能与 `sha256sum` 对上（CRLF 暴露"归一化文本摘要"的差异）。"""
    root = tmp_path / "daily-903"
    draft = root / "drafts" / "art-001"
    draft.mkdir(parents=True)
    body = draft / "body_draft.md"
    body.write_bytes("第一行\r\n第二行\r\n".encode("utf-8"))

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["articles"][0]["body_sha256"] == hashlib.sha256(body.read_bytes()).hexdigest()


def test_failure_reason_path_shares_the_body_path_base(tmp_path: Path, env: Path):
    """L2R3-06：同一条失败记录里 reason 的路径要与 body_path 同基，否则无法互查。"""
    root = tmp_path / "daily-904"
    draft = root / "drafts" / "art-001"
    draft.mkdir(parents=True)
    (draft / "body_draft.md").write_bytes(b"\xff\xfe")

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert article["body_path"] == "drafts/art-001/body_draft.md"
    assert article["reason"] == f"body_not_utf8:{article['body_path']}"


def test_rules_sha256_scope_is_explicit(tmp_path: Path, env: Path):
    """L2R3-07：不参与加载的子目录词库 → sha256 不变，但 dir_sha256/extra_files 必变。"""
    (env / "my-rules.md").write_text(MY_RULES_FAKE_CERT, encoding="utf-8")
    before = publish_precheck.rules_identity(env)

    sub = env / "wordlists" / "sub"
    sub.mkdir(parents=True)
    (sub / "deep.md").write_text("深层词\n", encoding="utf-8")
    after = publish_precheck.rules_identity(env)

    assert after["sha256"] == before["sha256"]  # 加载集没变（这是 sha256 的真实口径）
    assert after["sha256_scope"] == "loaded_rules_only"
    assert after["dir_sha256"] != before["dir_sha256"]  # 目录变了必须能看出来
    assert after["file_count"] == before["file_count"] + 1
    assert "wordlists/sub/deep.md" in after["extra_files"]


# ------------------------------------------------- 第 4 轮复核（L2R4-*）


def test_non_ascii_drafts_dir_title_is_scanned(tmp_path: Path, env: Path):
    """L2R4-01：**写**路径白名单不许当**读**路径的门。

    初版 `_selected_title()` 首行 `if not safe_article_id(article_id): return "", ""` ——
    目录名含中文等非白名单字符的稿件，标题子扫描"查都不查"就消失，记录与"这篇本来没有
    标题包"逐字段同形，丢的正是 G14 唯一检查面。
    """
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="解说稿-001")
    pack = root / "review" / "解说稿-001"
    pack.mkdir(parents=True)
    (pack / "title-pack.json").write_text(
        json.dumps({"directions": [{"title": "TITLE_MARKER 的标题", "selected": True}]}),
        encoding="utf-8",
    )

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert article["article_id"] == "解说稿-001"
    assert article["status"] == "ran"
    assert article["title"]["text"] == "TITLE_MARKER 的标题"
    assert article["title"]["status"] == "ran"
    assert record["totals"]["title_failed"] == 0

    # 对照：ASCII 目录名同版式行为**一致**（不允许"ASCII 查、中文不查"）
    control = tmp_path / "daily-911"
    (control / "drafts" / "art-001").mkdir(parents=True)
    (control / "drafts" / "art-001" / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    (control / "review" / "art-001").mkdir(parents=True)
    (control / "review" / "art-001" / "title-pack.json").write_text(
        json.dumps({"directions": [{"title": "TITLE_MARKER 的标题", "selected": True}]}),
        encoding="utf-8",
    )
    ctl = publish_precheck.build_publish_precheck_advisory(control)
    assert ctl["articles"][0]["title"]["text"] == "TITLE_MARKER 的标题"
    assert ctl["articles"][0]["status"] == "ran"


def test_dot_parent_directory_does_not_hide_articles(tmp_path: Path, env: Path):
    """L2R4-02：run 根嵌在点开头目录下时，不许把所有稿件静默滤光成"没有稿件"。"""
    root = tmp_path / ".hidden" / "rH"
    draft = root / "drafts" / "art-001"
    draft.mkdir(parents=True)
    (draft / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "ran"
    assert record["totals"]["articles"] == 1
    assert record["totals"]["scanned"] == 1


def test_symlinked_draft_dir_is_path_escape_not_ran(tmp_path: Path, env: Path):
    """L2R4-03：`drafts/<x>` 指向 run 外必须被拒（与声明版式同一道 `_within`）。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    root = tmp_path / "daily-905"
    (root / "drafts").mkdir(parents=True)
    (root / "drafts" / "art-001").symlink_to(outside, target_is_directory=True)

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert article["body_path"] == ""
    assert article["reason"].startswith("path_escape:")
    assert record["status"] == "error"
    assert any("path_escape" in error for error in record["errors"])


def test_non_utf8_my_rules_is_not_reported_as_zero_rules(tmp_path: Path, env: Path):
    """L2R4-04 + 第 10 轮 F2：读不出来的 `my-rules.md` 不许报成"零黑名单规则"。

    第 10 轮把这条从「ran + note」升级成「error + rules_unstaged」—— 文件**在位**却读不出来
    就是"规则在位却一条没装载"，与"这份规则库还没写过 my-rules.md"必须可区分。
    """
    (env / "my-rules.md").write_bytes(b"\xff\xfe\x00not utf-8 at all")

    info = publish_precheck.rules_identity(env)
    assert info["blacklist_unreadable"].startswith("not_utf8:")
    assert info["blacklist_rows"] == 0

    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
    assert record["status"] == "error"
    assert record["reason"].startswith("rules_unstaged:")
    assert "读不出来" in record["reason"]
    assert record["errors"] and record["errors"][0].startswith("rules_unstaged:")
    assert record["totals"]["scanned"] == 0


def test_rejected_manifest_id_leaves_a_trace(tmp_path: Path, env: Path):
    """L2R4-01 姊妹洞：manifest 里的 id 过不了**写**路径白名单时不许无痕退化。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT, case_id="解说稿-001")
    record = publish_precheck.build_publish_precheck_advisory(root)

    article = record["articles"][0]
    assert article["article_id"] == root.name
    assert article["article_id_note"] == "run_dir_name"
    assert article["reason"] == "id_unverified:id_rejected:pilot-manifest.json:case_id"
    assert article["status"] == "partial"


def test_scan_failure_reason_is_single_line_and_bounded():
    """L2R4-07 + L2R5-03：`reason` 是机器消费字段，不许内嵌 vendor 的多行回溯；
    被截断时必须留摘要 —— 否则"前 160 字符相同、差异在更后面"的两类故障会塌成同一个串。"""
    raw = "Traceback (most recent call last):\n" + '  File "x", line 1\n' * 40 + "ValueError: boom\t\x00"
    detail = publish_precheck._reason_detail(raw)
    for bad in ("\n", "\t", "\x00", "\r"):
        assert bad not in detail
    assert len(detail) <= 160
    assert "…+" in detail

    head = "boom " * 40
    assert publish_precheck._reason_detail(head + "A") != publish_precheck._reason_detail(head + "B")

    assert publish_precheck._reason_detail("") == "no_detail"
    assert publish_precheck._reason_detail("a", "b") == "a b"


# ------------------------------------------------ L2R5-01：清单要逐条校验


def test_tampered_scan_py_is_error_not_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R5-01：把真正产出候选的 `scripts/scan.py` 换成"永远零候选"的桩 —— 清单没动。

    初版只比对 `scripts/terms.json` 一行，于是这种替换会落成 `ran` + 0 候选 + 无告警，
    正是本层要拦的"假阴性被读成干净"。
    """
    fake = _fake_skill(
        tmp_path,
        "import sys, json; sys.stdout.write(json.dumps({'candidates': []}))\n",
        name="tampered-scan",
        manifest_paths=("scripts/scan.py", "scripts/terms.json"),
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    (fake / "scripts" / "scan.py").write_text("print('stub')\n", encoding="utf-8")

    root = _write_run(tmp_path, CRITICAL_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    # 顶层只汇总；具体病因在逐篇报告与 errors 里（与 terms 失败同一模式）
    assert record["reason"] == "all_scans_failed"
    assert record["articles"][0]["reason"] == "vendor_manifest_hash_mismatch:scripts/scan.py"
    assert any("vendor_manifest_hash_mismatch:scripts/scan.py" in e for e in record["errors"])
    assert record["totals"]["scanned"] == 0  # 与"扫过且 0 候选"区分开
    assert record["vendor_manifest"]["ok"] is False
    # L2R7-04：`checked` = "存在且逐字节相符"的条目数，`unique_count` = "去重后参与核验"
    # 的条目数 —— scan.py 被换掉，于是 checked=1（只剩 terms.json）而 unique_count=2。
    assert record["vendor_manifest"]["checked"] == 1
    assert record["vendor_manifest"]["unique_count"] == 2

    code = publish_precheck.main(["--run-root", str(root), "--json"])
    assert code == 1


def test_missing_listed_vendor_file_is_error_not_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """清单里列了但磁盘上没有的文件 → error（缺一条就是校验缺席，不是通过）。"""
    fake = _fake_skill(
        tmp_path,
        "pass\n",
        name="missing-file",
        manifest_paths=("scripts/scan.py", "scripts/terms.json", "references/judgment.md"),
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    (fake / "references" / "judgment.md").unlink()

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "all_scans_failed"
    assert record["articles"][0]["reason"] == "vendor_manifest_missing:references/judgment.md"
    assert record["vendor_manifest"]["missing"] == ["references/judgment.md"]


def test_vendor_manifest_entry_for_dotted_dir_is_not_mangled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """`.lstrip("./")` 是字符集裁剪：`./.github/x` 会被剥成 `github/x` 造成假阳性。

    第一版 `verify_vendor_manifest` 就是这么错的（真实 vendor 清单里恰好有 `./.gitignore`
    与 `./.github/**`，会被误报成"文件缺失"）。这里把点开头目录写进清单钉住。
    """
    fake = _fake_skill(
        tmp_path,
        "pass\n",
        name="dotted-dir",
        manifest_paths=("scripts/scan.py", "scripts/terms.json", ".github/workflows/ci.yml"),
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is True, info
    assert info["checked"] == 3
    assert info["mismatched"] == [] and info["missing"] == []

    root = _write_run(tmp_path, CLEAN_TEXT)
    assert publish_precheck.build_publish_precheck_advisory(root)["status"] == "error"  # scan 桩不是真扫描器
    # 但报错原因必须是"扫描器跑不动"，**不是**清单缺 .github
    assert publish_precheck.verify_vendor_manifest(fake)["ok"] is True


def test_vendor_manifest_checked_count_matches_real_vendor():
    """真实 vendor：清单 36 条逐条对得上（这条用仓库现成的只读 vendor）。"""
    real = publish_precheck.skill_dir()
    if not (real / "VENDOR.sha256").is_file():
        pytest.skip("vendor 不在仓库内")
    info = publish_precheck.verify_vendor_manifest(real)
    assert info["ok"] is True, info
    assert info["checked"] >= 30
    assert info["missing"] == [] and info["mismatched"] == []


def test_garbage_scanner_output_carries_stdout_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R5-03：`scan_output_not_json` 要留 stdout 摘要，否则只剩异常类型、无法取证。"""
    fake = _fake_skill(tmp_path, "import sys; sys.stdout.write('not json at all')\n")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    reason = record["articles"][0]["reason"]
    assert reason.startswith("scan_output_not_json:")
    assert "not json at all" in reason


# ------------------------------------------------- 第 6 轮复核回归（L2R6-01..05）


def test_manifest_with_required_entry_deleted_is_error_not_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R6-01（major）：**清单里那一行被删掉**时，逐条校验管不着。

    把 `VENDOR.sha256` 里的 `./scripts/scan.py` 行删掉、文件换成"永远零候选"的桩：
    第 5 轮的逐条校验会落成 `checked` 36→35、`missing=[]`、`mismatched=[]`、
    `ok=true`、`ran` + 候选 0 + `errors=[]` —— 不需要哈希知识，删一行就够。
    现在 `REQUIRED_MANIFEST_ENTRIES` 反向强制：该在清单上的没在，就是 error。
    """
    fake = _fake_skill(
        tmp_path,
        "import sys, json; sys.stdout.write(json.dumps({'candidates': []}))\n",
        name="deleted-line",
        manifest_paths=("scripts/terms.json",),  # 只列词表：等价于"删掉 scan.py 那一行"
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    (fake / "scripts" / "scan.py").write_text("print('zero-candidate stub')\n", encoding="utf-8")

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["required_missing"] == ["scripts/scan.py"]
    assert info["reason"] == "vendor_manifest_lacks_required_entry:scripts/scan.py"
    assert info["checked"] == 1  # 只剩词表那一条被核验

    root = _write_run(tmp_path, CRITICAL_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "all_scans_failed"
    assert (
        record["articles"][0]["reason"]
        == "vendor_manifest_lacks_required_entry:scripts/scan.py"
    )
    assert record["totals"]["scanned"] == 0  # 绝不能落成"扫过且 0 候选"
    assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1


def test_manifest_duplicate_entry_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R6-05：重复一行会让 `checked` 虚增（36→37），"多了一条"必须报出来。"""
    fake = _fake_skill(tmp_path, "pass\n", name="dupe-line")
    manifest = fake / "VENDOR.sha256"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest.write_text("\n".join(lines + lines[:1]) + "\n", encoding="utf-8")

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["duplicate_entries"] == ["scripts/scan.py"]
    assert info["reason"] == "vendor_manifest_duplicate_entry:scripts/scan.py"
    assert info["listed"] == 3 and info["unique_count"] == 2 and info["checked"] == 2


def test_manifest_uppercase_digest_is_not_silently_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R6-05：清单摘要 `.lower()` 与词表精确比较口径不一 → `ok=true` 与 `error` 并存。

    实测：36 行摘要全改大写时 `vendor_manifest.ok=true` 而 `status=error`
    （terms 精确比较先炸）—— 同一份清单两套尺子。现在统一为大小写敏感，
    仅大小写不同时给可区分的 `hash_case_mismatch`。
    """
    fake = _fake_skill(tmp_path, "pass\n", name="upper-digest")
    manifest = fake / "VENDOR.sha256"
    # 只把**摘要**改大写（整文件 .upper() 会连路径一起改，那是另一种故障）
    manifest.write_text(
        "\n".join(
            " ".join([line.split()[0].upper(), line.split()[1]])
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        + "\n",
        encoding="utf-8",
    )

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["mismatched"] == []
    assert info["mismatched_case_only"] == ["scripts/scan.py", "scripts/terms.json"]
    assert info["reason"].startswith("vendor_manifest_hash_case_mismatch:")


def test_manifest_entries_may_not_escape_or_carry_control_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R6-04：清单路径不能被原样信任 —— 越界不该被哈希，NUL 不该进记录。"""
    fake = _fake_skill(tmp_path, "pass\n", name="unsafe-entry")
    outside = tmp_path / "outside.txt"
    outside.write_text("run 之外的文件\n", encoding="utf-8")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    manifest = fake / "VENDOR.sha256"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + f"{digest}  ../outside.txt\n"
        + f"{digest}  ref\x00s.md\n",
        encoding="utf-8",
    )

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["checked"] == 2  # 越界与 NUL 两条都没有被计入"已核验"
    assert info["missing"] == [] and info["mismatched"] == []
    assert info["rejected_entries"] == ["3:path_escape", "4:control_char"]
    assert "\x00" not in json.dumps(info, ensure_ascii=False)
    assert info["reason"] == "vendor_manifest_rejected_entry:3:path_escape"


def test_manifest_absolute_entry_is_rejected_and_not_echoed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """绝对路径条目：拒绝，且记录里不出现宿主路径（第 6 轮实测它曾被真哈希）。"""
    fake = _fake_skill(tmp_path, "pass\n", name="abs-entry")
    outside = tmp_path / "abs-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    manifest = fake / "VENDOR.sha256"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + f"{digest}  {outside}\n", encoding="utf-8"
    )

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["rejected_entries"] == ["3:path_escape"]
    blob = json.dumps(info, ensure_ascii=False)
    assert str(outside) not in blob
    assert str(tmp_path) not in blob


def test_stdout_snippet_separates_outputs_sharing_the_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R6-03：只取首行时，首行相同的两个坏输出 `reason` 逐字节相同（46 字符，摘要分支不触发）。"""
    reasons = []
    for tag in ("AAA", "BBB"):
        fake = _fake_skill(
            tmp_path / f"skill-{tag}",
            f"import sys; sys.stdout.write('BROKEN-HEAD\\n{tag}-detail')\n",
            name=f"badout-{tag}",
        )
        monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
        root = _write_run(tmp_path / f"run-{tag}", CLEAN_TEXT)
        record = publish_precheck.build_publish_precheck_advisory(root)
        reasons.append(record["articles"][0]["reason"])

    assert reasons[0].startswith("scan_output_not_json:")
    assert "BROKEN-HEAD" in reasons[0]
    assert reasons[0] != reasons[1]


def test_stdout_snippet_truncates_with_digest_for_long_output():
    """超长 stdout：限长 + 全段摘要，仍是单行且有界。"""
    short = publish_precheck._stdout_snippet("x" * 10)
    assert short == "x" * 10
    long_a = publish_precheck._stdout_snippet("y" * 500)
    long_b = publish_precheck._stdout_snippet("y" * 499 + "z")
    assert len(long_a) <= 80 and len(long_b) <= 80
    assert "\n" not in long_a
    assert long_a != long_b
    assert publish_precheck._stdout_snippet("") == "<空 stdout>"
    assert publish_precheck._stdout_snippet("\n\n  \n") == "<空 stdout>"


# ------------------------------------------------- 第 7 轮（L2R7-01 ~ L2R7-06）


@pytest.mark.parametrize("linkout", [True, False])
def test_pilot_draft_symlink_is_not_silently_no_articles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path, linkout: bool
):
    """L2R7-01：pilot 版式 `draft.md` 变成软链时不许落成良性 `no_articles_to_scan`。

    指向 run **外**：原先 `is_file() and _within(...)` 同时失败 → `not_run` + `errors=[]` +
    退出 0，记录事实上声称"没有稿件"（稿件在，只是被拒扫）；指向 run **内**：本来就该照扫。
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "body.md"
    target.write_text(CRITICAL_TEXT, encoding="utf-8")

    root = tmp_path / "dsh-pilot-case-901"
    root.mkdir()
    (root / "draft.md").symlink_to(target if linkout else (root / "_real.md"))
    if not linkout:
        (root / "_real.md").write_text(CRITICAL_TEXT, encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    if linkout:
        assert record["status"] == "error"
        assert record["articles"][0]["reason"] == "path_escape:draft.md"
        assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1
    else:
        assert record["status"] == "ran"
        assert record["totals"]["candidates"] >= 1  # 软链只是"换个位置"，不是"没稿件"


def test_vendor_stdout_with_invalid_utf8_is_structured_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R7-02：vendor 输出含非 UTF-8 字节时，strict 解码抛的 UnicodeDecodeError
    （ValueError 子类）原先穿透 `scan_text`，整篇报告与病因全丢。现在结构化。"""
    fake = _fake_skill(
        tmp_path,
        "import sys\n"
        "sys.stdout.buffer.write(b'{\"candidates\": []}\\xff\\xfe')\n",
        name="binary-out",
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"].startswith("scan_output_not_utf8:")
    assert record["totals"]["scanned"] == 0
    assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1


def test_manifest_entry_with_c1_control_or_too_long_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R7-03：C1 控制字符（U+0080–U+009F）与超长路径都要像 NUL 一样被拒且不回显。"""
    fake = _fake_skill(tmp_path, "pass\n", name="c1-entry")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    manifest = fake / "VENDOR.sha256"
    base = manifest.read_text(encoding="utf-8").rstrip("\n").split("\n")
    manifest.write_text(
        "\n".join(base + [f"{'0' * 64}  bad\u009bname.md", f"{'0' * 64}  {'x' * 2000}.md"]) + "\n",
        encoding="utf-8",
    )

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is False
    assert info["rejected_entries"] == ["3:control_char", "4:too_long"]
    assert "\u009b" not in json.dumps(info)  # 原内容不进记录
    assert "x" * 100 not in json.dumps(info)


def test_manifest_line_splitting_is_not_confused_by_unicode_line_breaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R7-03：`splitlines()` 会在 NEL（U+0085）/U+2028 断行，从而伪造条目并让行号失真。"""
    fake = _fake_skill(tmp_path, "pass\n", name="nel-entry")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    manifest = fake / "VENDOR.sha256"
    base = manifest.read_text(encoding="utf-8").rstrip("\n").split("\n")
    manifest.write_text("\n".join(base + [f"{'0' * 64}  a\u0085b.md"]) + "\n", encoding="utf-8")

    info = publish_precheck.verify_vendor_manifest(fake)
    # NEL 不再断行：这一行仍是"一行且列数不对/含控制字符"，总之不产生额外条目
    assert info["listed"] == len(base) + 1
    assert len(info["malformed_lines"]) + len(info["rejected_entries"]) == 1


def test_manifest_binary_marker_then_dot_slash_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R7-06：`sha256sum -b` 的 `*` 与 `./` 叠成 `*./x` 时，合法清单不该被误判缺条目。"""
    fake = _fake_skill(tmp_path, "pass\n", name="star-dot")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    manifest = fake / "VENDOR.sha256"
    manifest.write_text(
        "\n".join(
            f"{line.split()[0]} *{line.split()[1]}" if line.split()[1].startswith("./")
            else line
            for line in manifest.read_text(encoding="utf-8").strip().split("\n")
        )
        + "\n",
        encoding="utf-8",
    )

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["ok"] is True, info
    assert info["required_missing"] == []


def test_manifest_checked_counts_only_verified_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R7-04：`checked` 是"已核验通过"，不是"去重后的条目数"（后者是 `unique_count`）。"""
    fake = _fake_skill(
        tmp_path, "pass\n", name="counts", manifest_paths=("scripts/scan.py", "scripts/terms.json")
    )
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    (fake / "scripts" / "scan.py").write_text("print('stub')\n", encoding="utf-8")

    info = publish_precheck.verify_vendor_manifest(fake)
    assert info["unique_count"] == 2 and info["checked"] == 1
    assert info["checked"] <= info["unique_count"] <= info["listed"]


def test_daily_engine_distinguishes_missing_from_unusable_record(tmp_path: Path):
    """L2R7-05：只有"文件不存在"是良性 not_run；目录/软链/缺 status 键都要带病因。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    (root / "review" / "gates").mkdir(parents=True)
    record = root / "review" / "gates" / "publish-precheck-advisory.json"

    assert engine.publish_precheck_advisory_status(root) == ("not_run", "")  # 还没跑过

    record.mkdir()
    assert engine.publish_precheck_advisory_status(root) == ("error", "record_not_a_file")
    record.rmdir()

    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps({"status": "ran"}), encoding="utf-8")
    record.symlink_to(outside)
    assert engine.publish_precheck_advisory_status(root) == ("error", "record_is_symlink")
    record.unlink()

    _write_advisory_record(root, "{}")
    assert engine.publish_precheck_advisory_status(root) == ("error", "record_missing_status")


def test_daily_engine_bounds_the_reason_field(tmp_path: Path):
    """L2R7-05：`reason` 原先原样透传，20 万字符能进 RUN-RECORD。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    _write_advisory_record(root, json.dumps({"status": "error", "reason": "x" * 200_000}))
    status, reason = engine.publish_precheck_advisory_status(root)
    assert status == "error"
    assert len(reason) <= 200 + 10
    assert "…+" in reason


# --------------------------------------------------------------- 第 8 轮（L2R8 家族）


@contextlib.contextmanager
def _deadline(seconds: float = 5.0):
    """给一段被测代码加硬超时：**挂死要报失败，不能把整个测试套件拖死**。

    L2R8-01 就是"永久阻塞"型缺陷（FIFO 上 `open()` 没有写端）—— 普通断言抓不到它，
    只会让 CI 卡住，所以这里用 `SIGALRM` 把"不返回"变成可读的 `TimeoutError`。
    """
    previous = signal.signal(signal.SIGALRM, _boom)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _boom(signum, frame):  # pragma: no cover - 只在被测代码挂死时触发
    raise TimeoutError("被测代码超过预算未返回（疑似阻塞在 open/read）")


def _declared_run(tmp_path: Path, name: str, rel: str) -> Path:
    """声明版式的最小 run：`publish-precheck.json` 指向 `rel`。"""
    root = tmp_path / name
    (root / "drafts").mkdir(parents=True)
    (root / "publish-precheck.json").write_text(
        json.dumps({"articles": {"art-fifo": rel}}), encoding="utf-8"
    )
    return root


def test_fifo_declared_body_is_rejected_without_blocking(tmp_path: Path, env: Path):
    """L2R8-01（major）：声明指向 **FIFO** 时 `read_text()` 永久阻塞 → `run_all_gates` 整轮挂死。

    同一条 FIFO 走 pilot 分支是立刻 `body_not_file` —— 所以这是"漏了一个分支"。
    """
    root = _declared_run(tmp_path, "run-fifo", "fifo-body.md")
    os.mkfifo(root / "fifo-body.md")

    with _deadline(5):
        record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "error"
    assert record["totals"]["scanned"] == 0
    assert record["articles"][0]["reason"].startswith("not_a_file:")
    with _deadline(5):
        assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1


def test_fifo_draft_body_is_not_silently_dropped(tmp_path: Path, env: Path):
    """L2R8-02：drafts 分支原先 `if not path.is_file(): continue` —— FIFO 被静默丢掉。

    若那是唯一一篇，记录会降级成**良性** `no_articles_to_scan` + rc=0。
    """
    root = tmp_path / "run-drafts-fifo"
    draft = root / "drafts" / "art-001"
    draft.mkdir(parents=True)
    os.mkfifo(draft / "body_draft.md")

    with _deadline(5):
        record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "error"  # 不是 not_run / no_articles_to_scan
    assert record["articles"][0]["reason"].startswith("not_a_file:")
    assert not record["errors"] == [] or record["articles"][0]["reason"]


def test_dangling_or_directory_declaration_is_not_read_as_absent(tmp_path: Path, env: Path):
    """L2R8-03：声明文件是目录/悬空软链时，原先当成"没声明"→ 范围**放大**成全扫 drafts。"""
    for kind in ("dir", "dangling"):
        root = _write_run(tmp_path / kind, CLEAN_TEXT)
        (root / "drafts" / "art-002").mkdir(parents=True)
        (root / "drafts" / "art-002" / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
        target = root / "publish-precheck.json"
        if kind == "dir":
            target.mkdir()
        else:
            target.symlink_to(root / "does-not-exist.json")

        record = publish_precheck.build_publish_precheck_advisory(root)

        assert record["status"] == "error", kind
        assert record["reason"].startswith("declaration_invalid:"), kind
        assert record["totals"]["scanned"] == 0, kind  # 没有被放大成扫 2 篇
        assert record["articles"] == [], kind


def test_dangling_manifest_and_title_pack_leave_traces(tmp_path: Path, env: Path):
    """L2R8-04：悬空 `pilot-manifest.json` / `title-pack.json` 原先静默当"没有"，仍报 ran。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT)
    (root / "pilot-manifest.json").unlink()
    (root / "pilot-manifest.json").symlink_to(root / "gone.json")
    (root / "title-pack.json").symlink_to(root / "gone-title.json")

    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "partial"
    # run 级 `reason` 只给粗类名（第 6 轮 L2R6-06 的消费契约），病因在逐篇报告与 errors 里。
    assert record["reason"] == "some_scans_failed"
    assert record["totals"]["title_failed"] == 1
    blob = json.dumps(record, ensure_ascii=False)
    assert "id_unverified:pilot-manifest.json_dangling_symlink" in blob
    assert "title_pack_dangling_symlink" in blob
    assert record["articles"][0]["title"]["reason"].startswith("title_pack_dangling_symlink")


def test_declaration_with_control_chars_never_reaches_the_record(tmp_path: Path, env: Path):
    """声明路径是外部输入：`path_escape:a\\x00b` 这种串以前真的进过 `reason`。"""
    root = _declared_run(tmp_path, "run-nul", "bad\x00name.md")

    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "error"
    assert "\x00" not in json.dumps(record, ensure_ascii=False)


def test_daily_engine_deeply_nested_record_is_error(tmp_path: Path):
    """L2R8-05：`json.loads` 对深层嵌套抛 **RecursionError**，原先逃出函数 → `batch.json` 写不出。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    _write_advisory_record(root, "[" * 200_000)
    assert engine.publish_precheck_advisory_status(root) == ("error", "record_too_deep")


# ------------------------------------------------------------------ 第 9 轮（L2R9）


def _forbidden_pass_keys(obj: object, path: str = "record") -> list[str]:
    """递归找**名为 `pass` 的键**（不变量 A 的机器判据：结构上不可能被读成通过）。"""
    hits: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "pass":
                hits.append(f"{path}.{key}")
            hits += _forbidden_pass_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            hits += _forbidden_pass_keys(value, f"{path}[{index}]")
    return hits


def test_vendor_non_regular_file_does_not_hang_the_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L2R9-02（major）：vendor 的 `scripts/terms.json` 指向 FIFO 时，`vendor_identity()`
    原先在生产路径上 `open()` 永久阻塞（`_sha256_file`）。现在必须秒回显式 error。"""
    fake = _fake_skill(tmp_path, "print('stub')\n")
    terms = fake / "scripts" / "terms.json"
    terms.unlink()
    os.mkfifo(terms)
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))

    root = _write_run(tmp_path, "普通正文，没有违禁词。")
    with _deadline(5):
        record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "vendor_not_a_file:scripts/terms.json"
    assert record["errors"] == ["vendor_not_a_file:scripts/terms.json"]
    assert record["totals"]["scanned"] == 0
    assert record["vendor"]["terms_sha256"] == ""


def test_vendor_fifo_scan_py_is_refused_without_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L2R9-02 的另一半：`scripts/scan.py` 是 FIFO 时，生产路径同样不许阻塞。"""
    fake = _fake_skill(tmp_path, "print('stub')\n")
    scan = fake / "scripts" / "scan.py"
    scan.unlink()
    os.mkfifo(scan)
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))

    root = _write_run(tmp_path, "普通正文，没有违禁词。")
    with _deadline(5):
        record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "not_run"
    assert record["reason"].startswith("skill_missing:")
    assert record["vendor"]["scan_sha256"] == ""


def test_cli_file_fifo_does_not_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """L2R9-03：`--file` 指向 FIFO 原先永久阻塞（与 L2R8-01 同一把 `open()`）。"""
    monkeypatch.setenv(
        publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, "print('stub')\n"))
    )
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))
    fifo = tmp_path / "body.md"
    os.mkfifo(fifo)

    with _deadline(5):
        code = publish_precheck.main(["--file", str(fifo), "--json"])
    record = json.loads(capsys.readouterr().out)
    assert code == 1
    assert record["status"] == "error"
    assert record["reason"].startswith("body_not_a_file:")
    assert record["errors"] == [record["reason"]]


def test_declared_absolute_and_dotdot_paths_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R9-04：绝对路径与含 `..` 的声明路径，即使解析后仍在 run 内，也按字面形态拒掉。"""
    monkeypatch.setenv(
        publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, "print('stub')\n"))
    )
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))
    root = _write_run(tmp_path, "普通正文。")
    body = root / "drafts" / "art-001" / "body_draft.md"
    (root / "publish-precheck.json").write_text(
        json.dumps(
            {
                "articles": {
                    "abs": str(body),
                    "dotdot": "drafts/art-001/../art-001/body_draft.md",
                }
            }
        ),
        encoding="utf-8",
    )
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["totals"]["scanned"] == 0
    assert len(record["errors"]) == 2
    assert all("path_escape" in error for error in record["errors"]), record["errors"]


def test_vendor_pass_key_cannot_reach_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R9-05：候选项只投影白名单字段 —— vendor 输出里的 `pass` / `status` / `verdict`
    不许进记录（不变量 A 不能依赖 vendor 的善意）。"""
    payload = {
        "characters": 12,
        "candidates": [
            {
                "match": "稳赚不赔",
                "start": 0,
                "end": 4,
                "line": 1,
                "context": "稳赚不赔",
                "rule": "fake-R01",
                "title": "绝对化用语",
                "severity": "high",
                "doc": "rules-common.md",
                "muted_by_whitelist": False,
                "pass": True,
                "status": "pass",
                "verdict": "pass",
            }
        ],
        "personal_hits": [
            {
                "match": "假证",
                "start": 0,
                "end": 2,
                "line": 1,
                "context": "假证",
                "reason": "自定黑名单",
                "level": "高",
                "mode": "black",
                "pass": True,
            }
        ],
        "myth_advisories": [],
        "warnings": [],
    }
    body = "import json\nprint(json.dumps(" + repr(payload) + "))\n"
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, body)))
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))
    root = _write_run(tmp_path, "稳赚不赔，包过。")

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert record["status"] == "ran"
    assert article["candidate_count"] == 1
    assert set(article["candidates"][0]) <= set(publish_precheck._VENDOR_CANDIDATE_KEYS)
    assert set(article["personal_hits"][0]) <= set(publish_precheck._VENDOR_PERSONAL_KEYS)
    assert sorted({"pass", "status", "verdict"} - set(article["dropped_vendor_keys"])) == []
    assert _forbidden_pass_keys(record) == []


def test_deep_but_parseable_advisory_record_is_error(tmp_path: Path):
    """L2R9-01（major）：`json.loads` 之后读值/转字符串仍可能 RecursionError ——
    原先那段在 `try` 之外，会逃出函数、让 `batch.json` 写不出来。"""
    from scripts import daily_engine as engine

    root = tmp_path / "run"
    path = root / "review" / "gates" / "publish-precheck-advisory.json"
    path.parent.mkdir(parents=True)
    # 直接写文本构造：`json.dumps` 在同样深度自己就会溢出，借不了它。
    depth = 50_000
    path.write_text(
        '{"status": "error", "reason": ' + "[" * depth + "]" * depth + "}", encoding="utf-8"
    )
    assert engine.publish_precheck_advisory_status(root) == ("error", "record_too_deep")


# --------------------------------------------------------------------------------------
# 第 10 轮（L2R10-01 ~ -07）：`--text`/`--file` 记录形状、嵌套声明值、terms.json 第二读点、
# 标题包"在但给不出标题"、声明类型、写路径白名单、run 根标题包串味。
# --------------------------------------------------------------------------------------

VENDOR_INJECTION_PAYLOAD = {
    "characters": 5,
    "commercial": False,
    "industries": [],
    "candidates": [
        {
            "match": "稳赚不赔",
            "start": 0,
            "end": 4,
            "line": 1,
            "context": "稳赚不赔",
            "rule": "x.R01",
            "title": "绝对化用语",
            "severity": "high",
            "doc": "rules.md",
            "muted_by_whitelist": False,
            "pass": True,
            "status": "ok",
            "verdict": "approve",
        }
    ],
    "personal_hits": [],
    "myth_advisories": [],
    "warnings": [],
}


def _injection_scan_body() -> str:
    return "import json\nprint(json.dumps(" + repr(VENDOR_INJECTION_PAYLOAD) + "))\n"


def test_adhoc_cli_record_also_projects_vendor_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """L2R10-01（major）：`_adhoc_record` 是 L2R9-05 漏掉的**另一个**记录形状。

    `--text`/`--file` 的 CLI 记录原先也是 `dict(i)` 逐字复制 vendor 输出，于是 vendor 里
    一个 `pass` 键就把不变量 A 推翻（`--json` 里真的出现 `"pass": true`）。
    """
    monkeypatch.setenv(
        publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, _injection_scan_body()))
    )
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(_rules_with_entry(tmp_path)))

    rc = publish_precheck.main(["--text", "稳赚不赔，包过。", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    record = json.loads(out)
    # 不变量 A 的机器判据：**名为 `pass` 的键**一处都不许有（`dropped_vendor_keys` 里只留
    # 键名，那不是键 —— 第 9 轮就是这么判的）。
    assert _forbidden_pass_keys(record) == []
    article = record["articles"][0]
    assert set(article["candidates"][0]) <= set(publish_precheck._VENDOR_CANDIDATE_KEYS)
    assert {"pass", "status", "verdict"} <= set(article["dropped_vendor_keys"])


def test_nested_declaration_value_never_reaches_the_record(tmp_path: Path, env: Path):
    """L2R10-02：白名单键的**值**也要过白名单 —— 嵌套 mapping 会把伪造键带进落盘记录。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "publish-precheck.json").write_text(
        json.dumps({"enabled": {"pass": True, "verdict": "approve"}}), encoding="utf-8"
    )

    record = publish_precheck.build_publish_precheck_advisory(root)
    dumped = json.dumps(record, ensure_ascii=False)
    assert '"pass"' not in dumped
    assert '"verdict": "approve"' not in dumped
    assert record["declaration"].get("declaration_nested_keys") == ["enabled"]
    assert "enabled" not in record["declaration"]


def test_terms_table_fifo_does_not_hang(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L2R10-03：`verify_terms_table` 直接调时会在第二个读点挂死（L2R9-02 的漏半）。"""
    fake = _fake_skill(tmp_path, "print('{}')\n")
    terms = fake / "scripts" / "terms.json"
    terms.unlink()
    os.mkfifo(terms)
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    with _deadline(5):
        info = publish_precheck.verify_terms_table()
        hashed = publish_precheck._sha256_file(terms)
    assert hashed == ""
    assert info["ok"] is False
    assert info["reason"] == "terms_table_not_a_file"


@pytest.mark.parametrize(
    "pack",
    [
        {"directions": [{"selected": True}]},
        {"directions": []},
        {"selected_title": 123},
        {"directions": [{"selected": True, "title": "   "}]},
    ],
)
def test_title_pack_present_but_unusable_is_not_silent(tmp_path: Path, env: Path, pack: dict):
    """L2R10-04：包**在**却给不出标题，不许与"这篇本来没有标题包"逐字段同形（丢 G14 面）。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT)
    (root / "title-pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    article = record["articles"][0]
    assert record["status"] == "partial"
    assert record["totals"]["title_failed"] == 1
    assert article["title"]["status"] == "error"
    assert article["title"]["reason"].startswith("title_pack_")
    assert record["errors"]


@pytest.mark.parametrize(
    "decl",
    [
        {"enabled": "false"},
        {"enabled": 0},
        {"industries": "medical"},
        {"commercial": "false"},
    ],
)
def test_wrong_typed_declaration_keys_fail_closed(tmp_path: Path, env: Path, decl: dict):
    """L2R10-05：只有 `articles` 的类型在管；其余三键类型写错原先被静默忽略、照扫报 ran。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "publish-precheck.json").write_text(json.dumps(decl), encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"].startswith("declaration_invalid_type:")
    assert record["errors"] == [record["reason"]]
    assert record["totals"]["scanned"] == 0


def test_drafts_write_path_respects_the_id_whitelist(tmp_path: Path, env: Path):
    """L2R10-06：读路径不收白名单（L2R4-01），**写**路径必须收 —— 两处口径一致。"""
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="解说稿-001")
    written: list[str] = []

    record = publish_precheck.build_publish_precheck_advisory(
        root, write_article_reports=lambda path, payload: written.append(str(path))
    )
    assert record["status"] == "ran"  # 读：照扫（目录名含中文不再让标题面消失）
    assert written == []  # 写：被拒的 id 绝不进写路径


def test_run_root_title_pack_is_pilot_only(tmp_path: Path, env: Path):
    """L2R10-07：run 根标题包只属于单篇 pilot run；drafts 多篇不许共用（串味）。"""
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="art-001")
    second = root / "drafts" / "art-002"
    second.mkdir(parents=True)
    (second / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")
    pack = json.dumps({"selected_title": "根标题党速看"}, ensure_ascii=False)
    (root / "title-pack.json").write_text(pack, encoding="utf-8")

    record = publish_precheck.build_publish_precheck_advisory(root)
    assert len(record["articles"]) == 2
    assert [a["title"] for a in record["articles"]] == [None, None]
    assert record["totals"]["title_failed"] == 0  # 不是"坏"，是"不归它"

    # 同一份 run 根标题包在 pilot 单篇 run 里必须被读到
    pilot = _write_pilot_run(tmp_path / "pilot", CLEAN_TEXT)
    (pilot / "title-pack.json").write_text(pack, encoding="utf-8")
    pilot_record = publish_precheck.build_publish_precheck_advisory(pilot)
    assert pilot_record["articles"][0]["title"]["text"] == "根标题党速看"


# ===================================================== 第 11 轮（L2R11-01 … L2R11-10）


def _scanner(payload: object) -> str:
    """造一个"输出固定 JSON"的假扫描器（不依赖真 upstream 逻辑）。"""
    return "import json\nprint(json.dumps(" + repr(payload) + "))\n"


def _payload(**over: object) -> dict:
    base = {
        "characters": 12,
        "commercial": True,
        "industries": [],
        "candidates": [],
        "personal_hits": [],
        "myth_advisories": [],
        "warnings": [],
        "note": "",
    }
    base.update(over)
    return base


def _pass_key_paths(node: object, prefix: str = "") -> list[str]:
    """递归找**名为 `pass` 的键**（不变量 A 的判据：任何形状里都不许出现）。"""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) == "pass":
                found.append(path)
            found.extend(_pass_key_paths(value, path))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_pass_key_paths(value, f"{prefix}[{index}]"))
    return found


NESTED_PASS_VENDOR = _payload(
    candidates=[
        {
            "match": "稳赚不赔",
            "start": 0,
            "end": 4,
            "line": {"pass": True},
            "context": {"nested": {"pass": "yes"}},
            "rule": "commercial-expression.R01",
            "title": "绝对化用语",
            "severity": "critical",
            "doc": "rules-commercial.md",
            "muted_by_whitelist": False,
        }
    ],
    personal_hits=[
        {"match": "稳赚不赔", "reason": "why", "level": "高", "mode": [{"pass": True}]}
    ],
    myth_advisories=[
        {"match": "偏方", "myth": "m", "suggestion": {"pass": True}, "line": 1}
    ],
    warnings=[{"pass": True}],
)


def test_nested_pass_values_never_reach_any_shape(tmp_path: Path, monkeypatch, env: Path, capsys):
    """L2R11-02：白名单原先只过滤**键名** —— 值里的嵌套 `pass` 键会漏进四种形状。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    monkeypatch.setenv(
        publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, _scanner(NESTED_PASS_VENDOR)))
    )

    written: dict[str, object] = {}
    record = publish_precheck.build_publish_precheck_advisory(
        root, write_article_reports=lambda rel, value: written.__setitem__(rel, value)
    )
    assert record["status"] == "ran"

    # A1 run 级记录
    assert _pass_key_paths(record) == []
    # A4 逐篇证据
    rel = "review/art-001/publish-precheck.json"
    assert list(written) == [rel]
    assert _pass_key_paths(written[rel]) == []
    # 非标量值降级成留痕（键名进 dropped，值不透传）
    dropped = record["articles"][0]["dropped_vendor_keys"]
    assert "line[non_scalar:dict]" in dropped
    assert "context[non_scalar:dict]" in dropped
    assert "mode[non_scalar:list]" in dropped
    assert "suggestion[non_scalar:dict]" in dropped

    # A2 复核清单
    findings = publish_precheck.candidate_findings_for_reviewer(record)
    assert findings and _pass_key_paths(findings) == []
    assert findings[0]["line"] is None and findings[0]["surface"] == "body"

    # A3 CLI --json
    assert publish_precheck.main(["--run-root", str(root), "--json"]) == 0
    import json as _json

    stdout_record = _json.loads(capsys.readouterr().out)
    assert _pass_key_paths(stdout_record) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": [], "characters": 120},
        {"characters": 120, "candidates": None, "personal_hits": [], "myth_advisories": [], "warnings": []},
        {"characters": "120", "candidates": [], "personal_hits": [], "myth_advisories": [], "warnings": []},
        {"characters": 120, "candidates": [], "personal_hits": [], "myth_advisories": []},
        {"characters": 120, "candidates": {}, "personal_hits": [], "myth_advisories": [], "warnings": []},
    ],
)
def test_malformed_vendor_shape_is_error_not_ran(
    tmp_path: Path, monkeypatch, env: Path, payload: dict
):
    """L2R11-03：只验 `isinstance(Mapping)` 时，键改名 / `{}` / 缺键 / 错类型都报 `ran + 0 候选 + rc=0`。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    monkeypatch.setenv(
        publish_precheck.SKILL_DIR_ENV, str(_fake_skill(tmp_path, _scanner(payload)))
    )
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "error"
    assert record["articles"][0]["status"] == "error"
    assert record["articles"][0]["reason"].startswith("scan_output_malformed:")
    assert record["totals"].get("scanned", 0) == 0
    assert publish_precheck.main(["--run-root", str(root)]) == 1


def test_two_simultaneous_title_problems_report_the_firing_branch(tmp_path: Path, env: Path):
    """L2R11-04：多个标题包同时有问题时，报的必须是**真正产出空标题**的那条分支。"""
    root = _write_pilot_run(tmp_path, CLEAN_TEXT, case_id="case-900")
    (root / "review" / "case-900" / "title-pack.json").mkdir(parents=True)  # 问题 1：目录
    # 问题 2：run 根标题包给了 selected:true 但拿不出标题 —— 真正"开火"的分支在候选表末尾
    (root / "title-pack.json").write_text(
        json.dumps({"directions": [{"selected": True}]}), encoding="utf-8"
    )

    record = publish_precheck.build_publish_precheck_advisory(root)
    title = record["articles"][0]["title"]
    assert title["status"] == "error"
    assert title["reason"] == "title_pack_selected_title_empty:title-pack.json"
    assert title["reason"] != "title_pack_not_a_file:review/case-900/title-pack.json"
    assert record["status"] == "partial"
    assert record["totals"]["title_failed"] == 1
    assert publish_precheck.main(["--run-root", str(root)]) == 1


def test_industries_element_type_is_named_and_not_applied(tmp_path: Path, env: Path):
    """L2R11-06：`industries` 元素错类型原先被 `str()` 静默吞掉后**照常执行**。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / publish_precheck.DECLARATION_NAME).write_text(
        json.dumps({"industries": ["影视", 3]}), encoding="utf-8"
    )
    record = publish_precheck.build_publish_precheck_advisory(root)

    assert record["status"] == "error"
    assert record["reason"] == "declaration_invalid_type:industries[1]:int"
    assert record["articles"] == []
    assert publish_precheck.main(["--run-root", str(root)]) == 1


def test_article_id_reason_is_single_line_bounded_and_length_capped(tmp_path: Path, env: Path):
    """L2R11-07 / L2R11-09：坏 id 的 reason 必须单行且有界；`safe_article_id` 必须有长度上界。"""
    root = _write_run(tmp_path, CLEAN_TEXT)
    bad_id = "art\nINJECTED\x00" + "H" * 40
    (root / publish_precheck.DECLARATION_NAME).write_text(
        json.dumps({"articles": {bad_id: "drafts/art-001/body_draft.md"}}), encoding="utf-8"
    )
    record = publish_precheck.build_publish_precheck_advisory(root)
    reason = record["articles"][0]["reason"]

    assert reason.startswith("invalid_article_id:")
    assert "\n" not in reason and "\x00" not in reason
    assert len(reason) <= 200

    # 长度上界（原先无上界：128 个 H 也过）
    assert publish_precheck.safe_article_id("H" * 128) is True
    assert publish_precheck.safe_article_id("H" * 129) is False


def test_run_gates_bounds_advisory_crash_reason(tmp_path: Path, monkeypatch):
    """L2R11-08：接线里裸拼 exc 会把多行回溯原样漏进 run 级记录。"""
    from article_group import run_gates

    def boom(*args, **kwargs):
        raise ValueError("Z" * 5000 + "\nINJECTED-LINE")

    monkeypatch.setattr(run_gates, "build_publish_precheck_advisory", boom)
    writes: dict[str, object] = {}
    summary = run_gates.run_all_gates(
        tmp_path, lambda rel, value: writes.__setitem__(rel, value), fail_on_error=False
    )

    advisory = writes["review/gates/publish-precheck-advisory.json"]
    assert advisory["status"] == "error"
    assert "advisory_crashed:ValueError:" in advisory["reason"]
    assert "\n" not in advisory["reason"]
    assert "INJECTED-LINE" not in advisory["reason"]
    assert len(advisory["reason"]) <= 260
    assert summary["publish_precheck_advisory"] == "error"


def test_write_skipped_evidence_leaves_a_trace(tmp_path: Path, env: Path):
    """L2R11-10：`evidence_write_skipped` 原先只在源码里 —— 跳过的**事实**没有落进任何记录。"""
    root = _write_run(tmp_path, CLEAN_TEXT, article_id="ok-001")
    unsafe = root / "drafts" / "解说稿-001"
    unsafe.mkdir(parents=True)
    (unsafe / "body_draft.md").write_text(CLEAN_TEXT, encoding="utf-8")

    written: dict[str, object] = {}
    record = publish_precheck.build_publish_precheck_advisory(
        root, write_article_reports=lambda rel, value: written.__setitem__(rel, value)
    )

    assert record["status"] == "ran"
    assert list(written) == ["review/ok-001/publish-precheck.json"]
    assert record["write_skipped"] == ["解说稿-001:invalid_article_id"]
    assert "解说稿-001:invalid_article_id:evidence_write_skipped:unsafe_article_id" in record["errors"]
    assert "逐篇报告未写" in publish_precheck._format_summary(record)


def test_symlinked_write_container_is_refused_not_silently_written(tmp_path: Path, env: Path):
    """L2R11-10 / L2R10-04：写容器是软链时，原先只在 `read_text()` 之后才被 `_within` 拒绝。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "review").mkdir(parents=True, exist_ok=True)
    (root / "review" / "art-001").symlink_to(outside, target_is_directory=True)

    written: dict[str, object] = {}
    record = publish_precheck.build_publish_precheck_advisory(
        root, write_article_reports=lambda rel, value: written.__setitem__(rel, value)
    )
    assert written == {}
    assert record["write_refused"] == ["review/art-001/publish-precheck.json"]
    assert "write_refused:path_escape:review/art-001/publish-precheck.json" in record["errors"]
    assert list(outside.iterdir()) == []

    # 记录本身的容器同理：软链出去必须 raise，而不是写到 run 外
    (root / "review" / "gates").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError, match="write_refused:path_escape"):
        publish_precheck._write_record(root, {"status": "ran", "reason": ""})
    assert not (outside / "publish-precheck-advisory.json").exists()


# ------------------------------------------------- 第 12 轮（L2R12-01 / L2R12-02）

DEEP_JSON = "[" * 60_000 + "]" * 60_000
STUB_SCAN = "import sys; sys.stdout.write('{}')\n"


def test_deeply_nested_terms_table_is_structured_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R12-01：**哈希自洽**的 terms.json 里放 6 万层嵌套 → RecursionError 必须收成
    结构化 error。修前它会逃出 build()，CLI 只吐回溯（同族修法早就落在 daily_engine，
    那一轮没传播到本模块，于是五处 json.loads 全是裸 JSONDecodeError）。"""
    fake = _fake_skill(tmp_path, STUB_SCAN, terms=DEEP_JSON, name="deep-terms")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    info = publish_precheck.verify_terms_table()
    assert info["ok"] is False
    assert info["reason"] == "terms_table_too_deep"
    # 关键：这不是"被篡改的词表" —— 清单与词表逐字节相符，所以哈希闸不会先拦住它
    assert publish_precheck.verify_vendor_manifest()["ok"] is True

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    # run 级 reason 只给粗类名（L2R6-06 消费契约），具体病因在 errors[] 与逐篇 reason
    assert record["reason"] == "all_scans_failed"
    assert record["articles"][0]["reason"] == "terms_table_too_deep"
    assert "terms_table_too_deep" in json.dumps(record, ensure_ascii=False)
    assert publish_precheck.main(["--run-root", str(root), "--json"]) == 1


def test_deeply_nested_declaration_is_error_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R12-01 同族：坏声明必须是显式 error（这里走 `too_deep` 分支）。"""
    fake = _fake_skill(tmp_path, STUB_SCAN, name="deep-decl")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "publish-precheck.json").write_text(DEEP_JSON, encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "declaration_unreadable:too_deep"
    assert record["totals"]["scanned"] == 0


def test_deeply_nested_vendor_output_is_error_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R12-01 同族：vendor 吐超深 JSON → 结构化 error，不是回溯。"""
    body = 'import sys; sys.stdout.write("[" * 60000 + "]" * 60000)\n'
    fake = _fake_skill(tmp_path, body, name="deep-out")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["articles"][0]["reason"].startswith("scan_output_too_deep")


def test_deeply_nested_pilot_manifest_and_title_pack_leave_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R12-01 同族：pilot 的 manifest / 标题包超深嵌套也不能静默当"没有"。"""
    # 正文扫描必须成功，否则 build 根本走不到标题子扫描（那是另一条路径）
    fake = _fake_skill(tmp_path, SCANNER_BODY_OK_TITLE_FAILS, name="deep-pilot")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_pilot_run(tmp_path, CLEAN_TEXT)
    (root / "pilot-manifest.json").write_text(DEEP_JSON, encoding="utf-8")
    (root / "title-pack.json").write_text(DEEP_JSON, encoding="utf-8")
    record = publish_precheck.build_publish_precheck_advisory(root)
    dumped = json.dumps(record, ensure_ascii=False)
    assert "pilot-manifest.json_too_deep" in dumped
    assert "title_pack_too_deep" in dumped
    assert record["totals"]["title_failed"] == 1


def test_rejected_industries_do_not_leak_into_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: Path
):
    """L2R12-02：被拒的声明不许"拒了却仍然生效" —— 复核方实测修前
    `options.industries == ["3","medical"]`，而注释却写"根本不会被构建"。"""
    fake = _fake_skill(tmp_path, STUB_SCAN, name="industries-cli")
    monkeypatch.setenv(publish_precheck.SKILL_DIR_ENV, str(fake))

    root = _write_run(tmp_path, CLEAN_TEXT)
    (root / "publish-precheck.json").write_text(
        json.dumps({"industries": ["medical", 3]}), encoding="utf-8"
    )
    record = publish_precheck.build_publish_precheck_advisory(root)
    assert record["status"] == "error"
    assert record["reason"] == "declaration_invalid_type:industries[1]:int"
    assert record["options"]["industries"] == []
    assert "medical" not in json.dumps(record["options"], ensure_ascii=False)

    # 对照组：合法声明仍然生效（说明不是把 options 一关了之）
    (root / "publish-precheck.json").write_text(
        json.dumps({"industries": ["医疗"]}), encoding="utf-8"
    )
    record2 = publish_precheck.build_publish_precheck_advisory(root)
    assert record2["options"]["industries"] == ["医疗"]

    # CLI 通道同理：被拒的 --industry 不进 options
    record3 = publish_precheck.build_publish_precheck_advisory(root, declaration={})
    assert record3["options"]["industries"] == []


# --------------------------------------------------------------------------- R9-04
# 规则目录被挂成软链时，**相对路径**会被软链按自身目录解析 → 悬空 → vendor 加载空黑名单，
# 而 rules_identity() 仍如实报"13 条已装载 / can_match=True"。「记录说有规则、实际一条没装载」
# 是本层最怕的假干净，所以挂载一律 resolve()，并在挂载后补一道断言。


def test_relative_rules_path_is_resolved_before_symlink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill = _fake_skill(tmp_path, "print('stub')\n")
    rules = tmp_path / "rules"
    rules.mkdir()
    body = (
        "# 我的规则库\n\n## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n"
        "|---|---|---|---|---|\n| 私信我 | 导流 | 全部 | 高 | 语境判 |\n"
    )
    (rules / "my-rules.md").write_text(body, encoding="utf-8")
    dest = tmp_path / "skill-stage"

    # 传相对路径（正是 R9-04 的触发形态）
    publish_precheck.stage_workspace(skill, "rules", dest)

    staged = dest / "data" / "my-rules.md"
    assert staged.is_file()
    assert staged.read_text(encoding="utf-8") == body


BLACKLIST_ONE_ROW = (
    "# 我的规则库\n\n## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n"
    "|---|---|---|---|---|\n| 私信我 | 导流 | 全部 | 高 | 语境判 |\n"
)
BLACKLIST_HEADER_ONLY = (
    "# 我的规则库\n\n## 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n"
    "|---|---|---|---|---|\n"
)


def _broken_rules(tmp_path: Path, kind: str) -> Path:
    """三种**真实**形态（不是 monkeypatch 造的）：规则在位却一条也装载不到。"""
    rules = tmp_path / f"rules-{kind}"
    rules.mkdir(parents=True)
    if kind == "no-my-rules":
        return rules
    (rules / "my-rules.md").write_text(BLACKLIST_ONE_ROW, encoding="utf-8")
    if kind == "dangling":
        (rules / "my-rules.md").unlink()
        (rules / "my-rules.md").symlink_to(tmp_path / "gone.md")
    elif kind == "my-rules-is-dir":
        (rules / "my-rules.md").unlink()
        (rules / "my-rules.md").mkdir()
    elif kind == "chmod-000":
        rules.chmod(0o000)
    return rules


@pytest.mark.parametrize("kind", ["dangling", "my-rules-is-dir", "chmod-000"])
def test_rules_present_but_not_loaded_is_error_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
):
    """第 10 轮 F2（major）：R9-04 初版断言比的是自指软链后的同一文件（`samefile` 恒 True）
    → 不可达；三种真实"规则在位却装载不到"的形态仍报 `ran + 0 命中`。现在必须 error。"""
    skill = _fake_skill(tmp_path, "print('stub')\n")
    rules = _broken_rules(tmp_path, kind)
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))
    try:
        with pytest.raises(publish_precheck.RulesStagingError):
            publish_precheck.stage_workspace(skill, rules, tmp_path / f"stage-{kind}")

        result = publish_precheck.scan_text("私信我领课程", skill=skill, rules=rules)
        assert result["status"] == "error", f"{kind} 不该退化成 ran"
        assert result["reason"].startswith("rules_unstaged:")
        assert result["raw"] is None

        record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
        assert record["status"] == "error", f"{kind} 的 run 级记录不该是 {record['status']}"
        assert record["reason"].startswith("rules_unstaged:")
        assert record["errors"] and "rules_unstaged:" in record["errors"][0]
        assert record["totals"]["scanned"] == 0
    finally:
        if kind == "chmod-000":
            rules.chmod(0o755)


def test_my_rules_without_a_single_loaded_row_is_error_not_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """第 10 轮 F2 的一般形态：声明了黑名单区段却装载 0 行 —— 自查面是空的，必须显式报错。"""
    rules = tmp_path / "rules-zero-rows"
    rules.mkdir()
    (rules / "my-rules.md").write_text(BLACKLIST_HEADER_ONLY, encoding="utf-8")
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))

    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))

    assert record["status"] == "error"
    assert record["reason"].startswith("rules_unstaged:")
    assert record["rules"]["blacklist_rows"] == 0


def test_rules_dir_without_my_rules_is_still_ran_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """反面对照：整份规则库从没写过 `my-rules.md`（合法起步态）**不**升级成 error，
    但必须有 `can_match=False` + 「不是规则放行」的 note，与"扫过且干净"可区分。"""
    rules = _broken_rules(tmp_path, "no-my-rules")
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))

    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))

    assert record["status"] == "ran"
    assert record["rules"]["blacklist_rows"] == 0
    assert record["rules"]["can_match"] is False
    assert "不是**规则放行**" in (record.get("personal_rules_note") or "")


# --------------------------------------- 第 11 轮：规则侧的挂死与入口一致性


def _rules_copy(tmp_path: Path, name: str) -> Path:
    """真规则目录的副本（含 13 行黑名单），用于构造"规则在位却读不到"的真实形态。

    从 `repo_root()/references/publish-precheck` 复制（不走 `rules_data_dir()`：
    `env` fixture 已把 DATA_DIR 指向空的临时目录）。
    """
    source = publish_precheck.repo_root() / "references" / "publish-precheck"
    destination = tmp_path / name
    shutil.copytree(source, destination)
    return destination


def test_fifo_my_rules_is_error_not_hang(tmp_path: Path, env: Path, monkeypatch: pytest.MonkeyPatch):
    """第 11 轮 finding 1（major）：规则目录里放 FIFO 当 `my-rules.md`。

    `_source_my_rules_digest()` 原用 `os.path.lexists` 判"在不在"就 `read_bytes()` ——
    无写端 FIFO 上 `open()` **永久阻塞**（复核方 `timeout 15` 实测 rc=124、stdout/stderr 全空）。
    判型必须走 `stat`（本模块在正文/vendor 文件上已修过两次同一不变量）。
    """
    rules = _rules_copy(tmp_path, "rules-fifo")
    (rules / "my-rules.md").unlink()
    os.mkfifo(rules / "my-rules.md")
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))
    with _deadline(5):
        record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
    assert record["status"] == "error"
    assert record["reason"].startswith("rules_unstaged:")
    # `scan_text` 入口同样不许挂死（CLI `--text/--file` 走的就是它）。
    with _deadline(5):
        direct = publish_precheck.scan_text(CLEAN_TEXT, commercial=False, rules=rules)
    assert direct["status"] == "error"
    assert direct["reason"].startswith("rules_unstaged:")


def test_stage_workspace_rejects_fifo_my_rules(tmp_path: Path, env: Path):
    """直接调 `stage_workspace()` 也必须拒（不能只靠调用方记得先判型）。"""
    rules = _rules_copy(tmp_path, "rules-stage")
    (rules / "my-rules.md").unlink()
    os.mkfifo(rules / "my-rules.md")
    with _deadline(5):
        with pytest.raises(publish_precheck.RulesStagingError):
            publish_precheck.stage_workspace(
                publish_precheck.skill_dir(), rules, tmp_path / "work"
            )


def test_zero_row_my_rules_is_error_in_both_entry_points(
    tmp_path: Path, env: Path, monkeypatch: pytest.MonkeyPatch
):
    """第 11 轮 finding 2：`build` 与 `scan_text` 两个入口必须给同一个判定。

    0 行形态（有「黑名单」区段但一条没装载）原先 `build` → error、`scan_text` → `ran`+rc=0，
    文档 §12.9 的表只对一半入口成立。
    """
    rules = _rules_copy(tmp_path, "rules-zero")
    (rules / "my-rules.md").write_text(
        "# 黑名单\n\n| 词/正则 | 为什么 | 平台 | 级别 | 判法 |\n|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(publish_precheck.DATA_DIR_ENV, str(rules))
    record = publish_precheck.build_publish_precheck_advisory(_write_run(tmp_path, CLEAN_TEXT))
    direct = publish_precheck.scan_text(CLEAN_TEXT, commercial=False, rules=rules)
    assert record["status"] == "error" and record["reason"].startswith("rules_unstaged:")
    assert direct["status"] == "error" and direct["reason"].startswith("rules_unstaged:")
    assert "装载 0 行" in direct["reason"]


def test_non_utf8_my_rules_is_rules_unstaged_in_scan_text(tmp_path: Path, env: Path):
    """非 UTF-8 的 `my-rules.md`：`scan_text` 过去落到 `scan_exit_1:UnicodeDecodeError`
    （仍是 fail-closed，但病因不是"规则没装载"这一层），现在是同一条 `rules_unstaged:`。"""
    rules = _rules_copy(tmp_path, "rules-nonutf8")
    (rules / "my-rules.md").write_bytes(b"\xff\xfe\x00 not utf8\n")
    direct = publish_precheck.scan_text(CLEAN_TEXT, commercial=False, rules=rules)
    assert direct["status"] == "error"
    assert direct["reason"].startswith("rules_unstaged:")
    assert direct["rules"]["blacklist_unreadable"]


def test_fifo_wordlist_is_error_before_launching_vendor(tmp_path: Path, env: Path):
    """第 11 轮 finding 3：`wordlists/x.md` 是 FIFO 时上游 glob 无 `is_file()` 过滤 → vendor 挂住。

    适配器原先只能靠 `subprocess.run(timeout=120)` 兜底（最长 120 秒静默），
    现在在启动 vendor **之前**判型 fail-closed，并把文件列进 `wordlist_non_regular`。
    """
    rules = _rules_copy(tmp_path, "rules-wordfifo")
    os.mkfifo(rules / "wordlists" / "x.md")
    with _deadline(5):
        direct = publish_precheck.scan_text(CLEAN_TEXT, commercial=False, rules=rules)
    assert direct["status"] == "error"
    assert direct["reason"].startswith("rules_unstaged:")
    assert "wordlists 里有非普通文件" in direct["reason"]
    assert direct["rules"]["wordlist_non_regular"] == ["wordlists/x.md"]


def test_adhoc_json_carries_personal_rules_note(tmp_path: Path, env: Path, capsys):
    """第 11 轮 finding 2 的第三处：CLI（ad-hoc）记录过去从不带 `personal_rules_note`。

    无 `my-rules.md` 是合法起步态，但 CLI 输出里只剩 `可匹配=False` 一句 ——
    "自查 0 命中"容易被读成"规则放行"。现在两个记录形状共用同一份措辞。
    """
    rules = _rules_copy(tmp_path, "rules-adhoc")
    (rules / "my-rules.md").unlink()
    exit_code = publish_precheck.main(["--text", CLEAN_TEXT, "--no-commercial", "--json"])
    assert exit_code == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "ran"
    assert record["rules"]["can_match"] is False
    assert "不是**规则放行**" in (record.get("personal_rules_note") or "")

