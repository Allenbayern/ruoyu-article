import importlib.util
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_release_renderer.py"
UPSTREAM_ROOT = Path("/private/tmp/hermes-gzh-design-3ChZEA/gzh-design-skill")
EXPECTED_COMMIT = "ba1f4175519b481cb3566616c9e5178705067904"
EXPECTED_VALIDATOR_SHA256 = "de21aa3decac10c6ef89040bdc4e19930dbed33d6ccf7bc963b744c53da01185"


class TextLeafParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.leaf_depth = 0
        self.unwrapped_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "span" and "leaf" in dict(attrs):
            self.leaf_depth += 1

    def handle_endtag(self, tag):
        if tag == "span" and self.leaf_depth:
            self.leaf_depth -= 1

    def handle_data(self, data):
        if data.strip() and self.leaf_depth == 0:
            self.unwrapped_text.append(data.strip())


def load_module():
    spec = importlib.util.spec_from_file_location("daily3_release_renderer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def candidate(slot="A"):
    return {
        "id": f"{slot}-candidate",
        "headline": "一部电影如何把日常拍出重量",
        "body": "开场分析完整保留。\n\n【事实】这是来自核验来源的原始事实。\n\n结尾分析完整保留。",
        "evidence": {
            "claims": [{"claim_id": f"{slot}-claim", "text": "这是来自核验来源的原始事实。", "source_id": f"{slot}-claim", "locator": "root"}],
            "sources": [{"source_id": f"{slot}-claim", "url": "https://evidence.example/source", "quote": "这是来自核验来源的原始事实。", "locator": "root"}],
        },
    }


def test_render_release_article_strips_audit_markers_keeps_body_and_writes_evidence_separately(tmp_path):
    module = load_module()

    result = module.render_release_article(candidate=candidate())

    assert result["title"] == candidate()["headline"]
    assert module.cjk_count(result["title"]) <= 30
    assert "【事实】" not in result["html"]
    assert "claim-map" not in result["html"].lower()
    assert "provenance" not in result["html"].lower()
    assert "run/status" not in result["html"].lower()
    assert "这是来自核验来源的原始事实。" in result["html"]
    assert "开场分析完整保留。" in result["html"]
    assert "结尾分析完整保留。" in result["html"]
    assert "<h1" in result["html"].lower()
    assert re.search(r"<title[^>]*>.*?</title>", result["preview_html"], re.S)
    assert result["title"] in result["preview_html"]
    assert result["evidence"] == candidate()["evidence"]
    parser = TextLeafParser()
    parser.feed(result["html"])
    assert parser.unwrapped_text == []


def test_render_release_article_fails_closed_for_title_over_30_cjk():
    module = load_module()
    long_title = "中" * 31
    bad = candidate()
    bad["headline"] = long_title

    with __import__("pytest").raises(module.ReleaseRenderError, match="TITLE_CJK_LIMIT_EXCEEDED"):
        module.render_release_article(candidate=bad)


def test_render_release_article_rejects_release_text_policy_markers_in_headline_and_every_body_paragraph():
    module = load_module()

    for field, value in (
        ("headline", "【事实】一部电影如何把日常拍出重量"),
        ("body", "开场分析完整保留。\n\nclaim_map: audit"),
        ("body", "开场分析完整保留。\n\nclaim - map: audit"),
        ("body", "开场分析完整保留。\n\nrun_id: audit"),
        ("body", "开场分析完整保留。\n\npublication_ status"),
        ("body", "开场分析完整保留。\n\nstructural_gate: audit"),
        ("body", "开场分析完整保留。\n\n{{ template_placeholder }}"),
    ):
        bad = candidate()
        bad[field] = value

        with __import__("pytest").raises(module.ReleaseRenderError, match="RELEASE_TEXT_POLICY_FORBIDDEN"):
            module.render_release_article(candidate=bad)


def test_render_release_article_cleans_only_a_leading_fact_prefix_in_each_body_paragraph():
    module = load_module()
    clean = candidate()
    clean["body"] = "【 事实 】第一段。\n\n【事实】第二段。"

    result = module.render_release_article(candidate=clean)

    assert "【" not in result["html"]
    assert "第一段。" in result["html"]
    assert "第二段。" in result["html"]


def test_cli_rejects_audit_text_without_creating_output_or_temporary_artifacts(tmp_path):
    source = ROOT / "tmp" / "daily3-real-1905-20260718" / "adapter-output.json"
    for name, field, value in (
        ("fact-headline", "headline", "【事实】标题不得渲染"),
        ("claim-map-body", "body", "开场分析完整保留。\n\nclaim_map: audit"),
    ):
        input_path = tmp_path / f"{name}-input.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["slots"]["A"][0][field] = value
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        destination = tmp_path / name

        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(destination)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode != 0
        assert "RELEASE_TEXT_POLICY_FORBIDDEN" in completed.stderr
        assert not destination.exists()
    assert list(tmp_path.glob(".fact-headline.*")) == []
    assert list(tmp_path.glob(".claim-map-body.*")) == []


def test_cli_rejects_internal_audit_field_families_in_headlines_and_body_paragraphs_without_residue(tmp_path):
    """Audience text rejects internal audit field labels instead of deleting them.

    The contract applies case-insensitively and treats hyphen, underscore, slash,
    whitespace, and adjacent punctuation as common label separators. Each case is
    a real CLI run against the controlled three-slot adapter fixture.
    """
    source = ROOT / "tmp" / "daily3-real-1905-20260718" / "adapter-output.json"
    cases = (
        ("claim-id-headline", "A", "headline", "CLAIM-ID: A1"),
        ("source-id-body", "A", "body", "source_id: S1"),
        ("atom-id-body", "B", "body", "AtOm / Id = atom-1"),
        ("raw-sha256-body", "B", "body", "RAW SHA256: deadbeef"),
        ("raw-hash-body", "C", "body", "raw_hash = deadbeef"),
        ("audit-status-body", "C", "body", "AUDIT-STATUS: pass"),
        ("audit-state-body", "A", "body", "audit state: passed"),
    )
    for name, slot, field, value in cases:
        input_path = tmp_path / f"{name}-input.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        if field == "body":
            payload["slots"][slot][0][field] = f"首段保留普通叙述。\n\n{value}\n\n末段保留普通叙述。"
        else:
            payload["slots"][slot][0][field] = value
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        destination = tmp_path / name

        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(destination)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode != 0
        assert "RELEASE_TEXT_POLICY_FORBIDDEN" in completed.stderr
        assert not destination.exists()
        assert list(tmp_path.glob(f".{name}.*")) == []


def test_cli_renders_real_slots_as_nonaccepted_when_controlled_preview_is_unavailable(tmp_path):
    source = ROOT / "tmp" / "daily3-real-1905-20260718" / "adapter-output.json"
    destination = tmp_path / "release"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(destination)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publication_performed"] is False
    assert manifest["wechat_preview_verified"] is False
    assert manifest["coverage_gaps"] == ["No controlled WeChat-editor preview capability was available; local deterministic preflight is not preview verification."]
    assert manifest["release_acceptance"] == {
        "reason": "WECHAT_PREVIEW_UNVERIFIED",
        "status": "not_accepted",
    }
    for slot in "ABC":
        article = (destination / "slots" / slot / "article.html").read_text(encoding="utf-8")
        evidence = json.loads((destination / "slots" / slot / "evidence.json").read_text(encoding="utf-8"))
        assert "【事实】" not in article
        assert "claim-map" not in article.lower()
        assert "provenance" not in article.lower()
        assert evidence["claims"]
        assert evidence["sources"]


def test_local_deterministic_preflight_accepts_fragment_and_records_no_external_dependency():
    module = load_module()

    result = module.render_release_article(candidate=candidate())

    assert result["validator"] == {
        "kind": "local_deterministic_preflight",
        "validated": True,
    }
    assert result["wechat_preview_verified"] is False
    assert "external" not in json.dumps(result["validator"]).lower()


def test_local_deterministic_preflight_rejects_document_wrappers_scripts_and_event_attributes():
    module = load_module()

    for fragment in (
        "<!doctype html><html><body><section><span>bad</span></section></body></html>",
        "<section><span>bad</span><script>alert(1)</script></section>",
        '<section onclick="bad()"><span>bad</span></section>',
    ):
        with __import__("pytest").raises(module.ReleaseRenderError):
            module.validate_local_deterministic_preflight(fragment)


def test_cli_manifest_declares_local_deterministic_validation_mode(tmp_path):
    source = ROOT / "tmp" / "daily3-real-1905-20260718" / "adapter-output.json"
    destination = tmp_path / "release"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(destination)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation"] == {"mode": "local_deterministic_preflight"}
