import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_daily3_provenance.py"
DATE = "20260718"
SUBJECTS = ("37379599", "37242440", "36372941")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_atom(subject: str, suffix: str) -> dict:
    claim = f"作品{subject}的可核验事实{suffix}"
    return {
        "id": f"atom-{subject}-{suffix}",
        "claim": claim,
        "source_text": claim,
        "url": f"https://evidence.example/{subject}/{suffix}",
        "source_locator": "validated_editorial_root",
        "page_type": "news",
        "published_at": "2026-07-18",
        "fact_class": "production",
        "source_metadata": {
            "institution": "Evidence Desk",
            "source_program": None,
            "author": None,
            "reporters": [],
            "editors": [],
            "published_at": "2026-07-18",
        },
    }


def make_chain(tmp_path: Path) -> tuple[Path, Path, dict]:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    atoms = []
    for subject in SUBJECTS:
        packet = {
            "success": True,
            "status": "focused_live_verified",
            "work_identity": {
                "work_key": f"douban:{subject}",
                "title": f"作品{subject}",
            },
            "evidence_atoms": [raw_atom(subject, "one")],
        }
        raw_path = raw_dir / f"{subject}.json"
        raw_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
        packet_id = f"1905-editorial-{subject}-{DATE}"
        for atom in packet["evidence_atoms"]:
            atoms.append({
                **atom,
                "work_key": f"douban:{subject}",
                "origin_packet_id": packet_id,
                "origin_packet_sha256": digest(raw_path),
            })

    slots = {}
    for slot, subject, atom in zip("ABC", SUBJECTS, atoms):
        slots[slot] = [{
            "id": f"article-{slot}",
            "work_key": atom["work_key"],
            "origin_packet_id": atom["origin_packet_id"],
            "angle_key": f"angle-{slot}",
            "factual_claims": [{"atom_id": atom["id"], "text": atom["claim"]}],
        }]
    source = tmp_path / "source.json"
    payload = {"evidence_atoms": atoms, "slots": slots}
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return raw_dir, source, payload


def run_verifier(tmp_path: Path, raw_dir: Path, source: Path, *optional: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--raw-dir", str(raw_dir), "--source-input", str(source), *optional, "--output", str(tmp_path / "report.json")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_verifier_accepts_three_raw_packets_and_reports_skipped_optional_phases(tmp_path):
    raw_dir, source, _ = make_chain(tmp_path)

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["phases"]["adapter"] == "skipped"
    assert report["phases"]["gate"] == "skipped"
    assert [row["slot"] for row in report["matrix"]] == ["A", "B", "C"]
    assert {row["work_key"] for row in report["matrix"]} == {f"douban:{subject}" for subject in SUBJECTS}
    assert set(report["raw_packet_sha256"]) == set(SUBJECTS)


def test_verifier_rejects_source_atom_with_raw_hash_mismatch_and_leaves_no_report(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    payload["evidence_atoms"][0]["origin_packet_sha256"] = "0" * 64
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 1
    assert "SOURCE_RAW_SHA256_MISMATCH" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_verifier_rejects_1905_raw_identity_masquerading_as_douban_and_leaves_no_report(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    subject = SUBJECTS[0]
    raw_path = raw_dir / f"{subject}.json"
    raw_packet = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_packet["work_identity"] = {
        "work_key": f"1905:film:{subject}",
        "title": "1905 canonical identity",
    }
    raw_path.write_text(json.dumps(raw_packet, ensure_ascii=False), encoding="utf-8")
    payload["evidence_atoms"][0]["origin_packet_sha256"] = digest(raw_path)
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 1
    assert "SOURCE_WORK_KEY_RAW_IDENTITY_MISMATCH" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_verifier_rejects_source_metadata_mismatch_and_leaves_no_report(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    payload["evidence_atoms"][0]["source_metadata"]["institution"] = "Different Desk"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 1
    assert "SOURCE_ATOM_RAW_CONTENT_MISMATCH" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_verifier_accepts_1905_identity_with_unknown_catalog_page_date(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    subject = SUBJECTS[0]
    raw_path = raw_dir / f"{subject}.json"
    raw_packet = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_packet["work_identity"]["work_key"] = f"1905:film:{subject}"
    raw_packet["evidence_atoms"][0]["published_at"] = None
    raw_packet["evidence_atoms"][0]["source_metadata"]["published_at"] = None
    raw_path.write_text(json.dumps(raw_packet, ensure_ascii=False), encoding="utf-8")
    payload["evidence_atoms"][0]["work_key"] = f"1905:film:{subject}"
    payload["evidence_atoms"][0]["published_at"] = None
    payload["evidence_atoms"][0]["source_metadata"]["published_at"] = None
    payload["slots"]["A"][0]["work_key"] = f"1905:film:{subject}"
    payload["evidence_atoms"][0]["origin_packet_sha256"] = digest(raw_path)
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["matrix"][0]["work_key"] == f"1905:film:{subject}"


def test_verifier_rejects_atom_cited_by_two_slots_and_leaves_no_report(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    duplicated = payload["slots"]["A"][0]["factual_claims"][0]
    payload["slots"]["B"][0]["factual_claims"] = [duplicated]
    payload["slots"]["B"][0]["work_key"] = payload["slots"]["A"][0]["work_key"]
    payload["slots"]["B"][0]["origin_packet_id"] = payload["slots"]["A"][0]["origin_packet_id"]
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source)

    assert result.returncode == 1
    assert "DUPLICATE_SLOT_ATOM_ID" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_verifier_rejects_adapter_claim_provenance_mismatch(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    adapter = tmp_path / "adapter.json"
    slots = {}
    for slot, drafts in payload["slots"].items():
        draft = drafts[0]
        atom = next(atom for atom in payload["evidence_atoms"] if atom["id"] == draft["factual_claims"][0]["atom_id"])
        slots[slot] = [{
            "id": draft["id"],
            "work_key": draft["work_key"],
            "origin_packet_id": draft["origin_packet_id"],
            "evidence": {
                "claims": [{
                    "claim_id": atom["id"], "text": atom["claim"], "source_id": atom["id"],
                    "locator": atom["source_locator"], "work_key": atom["work_key"],
                    "origin_packet_id": atom["origin_packet_id"], "origin_packet_sha256": atom["origin_packet_sha256"],
                }],
                "sources": [{
                    "source_id": atom["id"], "quote": atom["claim"], "url": atom["url"],
                    "locator": atom["source_locator"], "work_key": atom["work_key"],
                    "origin_packet_id": atom["origin_packet_id"], "origin_packet_sha256": atom["origin_packet_sha256"],
                }],
            },
        }]
    slots["B"][0]["evidence"]["claims"][0]["origin_packet_sha256"] = "f" * 64
    adapter.write_text(json.dumps({"slots": slots}, ensure_ascii=False), encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source, "--adapter-output", str(adapter))

    assert result.returncode == 1
    assert "ADAPTER_CLAIM_PROVENANCE_MISMATCH" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_verifier_accepts_final_gate_directory_with_exact_evidence_and_both_article_formats(tmp_path):
    raw_dir, source, payload = make_chain(tmp_path)
    adapter = tmp_path / "adapter.json"
    slots = {}
    for slot, drafts in payload["slots"].items():
        draft = drafts[0]
        atom = next(atom for atom in payload["evidence_atoms"] if atom["id"] == draft["factual_claims"][0]["atom_id"])
        evidence = {
            "claims": [{"claim_id": atom["id"], "text": atom["claim"], "source_id": atom["id"], "locator": atom["source_locator"], **{key: atom[key] for key in ("work_key", "origin_packet_id", "origin_packet_sha256")}}],
            "sources": [{"source_id": atom["id"], "quote": atom["claim"], "url": atom["url"], "locator": atom["source_locator"], **{key: atom[key] for key in ("work_key", "origin_packet_id", "origin_packet_sha256")}}],
        }
        slots[slot] = [{"id": draft["id"], "work_key": draft["work_key"], "origin_packet_id": draft["origin_packet_id"], "evidence": evidence}]
    adapter.write_text(json.dumps({"slots": slots}, ensure_ascii=False), encoding="utf-8")
    gate = tmp_path / "gate"
    (gate / "manifest.json").parent.mkdir()
    (gate / "manifest.json").write_text(json.dumps({"status": "final", "publish_ready": True, "publication_performed": False}), encoding="utf-8")
    for slot in "ABC":
        slot_dir = gate / "slots" / slot
        slot_dir.mkdir(parents=True)
        (slot_dir / "evidence.json").write_text(json.dumps(slots[slot][0]["evidence"], ensure_ascii=False), encoding="utf-8")
        (slot_dir / "article.md").write_text("# draft\n", encoding="utf-8")
        (slot_dir / "article.html").write_text("<p>draft</p>\n", encoding="utf-8")

    result = run_verifier(tmp_path, raw_dir, source, "--adapter-output", str(adapter), "--gate-output", str(gate))

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["phases"] == {"raw_source": "passed", "adapter": "passed", "gate": "passed"}
