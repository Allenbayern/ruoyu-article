import hashlib
import importlib.util
import json
import shutil
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_today_delivery_ledger.py"
ORCHESTRATOR = ROOT / "scripts" / "daily3_production_orchestrator.py"
SOURCE_ROOT = ROOT / "outputs" / "daily3_today_source_research" / "20260720-repair-t_e67ffacb"


def load_module():
    spec = importlib.util.spec_from_file_location("daily3_today_delivery_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_orchestrator():
    spec = importlib.util.spec_from_file_location("daily3_production_orchestrator", ORCHESTRATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_record(**overrides):
    record = {
        "work_key": "1905:film:2258538",
        "source_bundle_sha256": "a" * 64,
        "article_content_sha256": "b" * 64,
        "source_packet_sha256": "c" * 64,
        "created_at": "2026-07-21T08:50:00Z",
        "delivery_status": "not_delivered",
    }
    record.update(overrides)
    return record


def baseline():
    return {
        "historical_delivery_ledger": "NOT_FOUND_AND_UNVERIFIABLE",
        "scope": "forward_only_from_2026-07-21",
        "created_at": "2026-07-21T08:50:00Z",
        "source_repair_artifact": "outputs/daily3_today_source_research/20260720-repair-t_e67ffacb",
    }


def synchronized_commits(module, ledger, records):
    writers_ready = threading.Barrier(len(records))
    errors = []

    def commit(record):
        try:
            writers_ready.wait(timeout=5)
            module.commit_ledger(ledger, record)
        except Exception as error:
            errors.append(error)

    writers = [threading.Thread(target=commit, args=(record,)) for record in records]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=10)
        assert not writer.is_alive()
    return errors


def test_commit_fails_closed_when_ledger_is_missing(tmp_path):
    module = load_module()

    with pytest.raises(module.LedgerFailure, match="DELIVERY_LEDGER_MISSING"):
        module.commit_ledger(tmp_path / "missing-ledger.json", committed_record())


def test_commit_fails_closed_when_ledger_is_corrupt(tmp_path):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    ledger.write_text("not-json", encoding="utf-8")

    with pytest.raises(module.LedgerFailure, match="DELIVERY_LEDGER_INVALID"):
        module.commit_ledger(ledger, committed_record())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("work_key", "1905:film:2258538"),
        ("source_bundle_sha256", "a" * 64),
        ("article_content_sha256", "b" * 64),
    ],
)
def test_commit_fails_closed_for_each_duplicate_identity(tmp_path, field, value):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    module.initialize_ledger(ledger, baseline())
    module.commit_ledger(ledger, committed_record())

    duplicate = committed_record(
        work_key="1905:film:2259172",
        source_bundle_sha256="d" * 64,
        article_content_sha256="e" * 64,
    )
    duplicate[field] = value

    with pytest.raises(module.LedgerFailure, match="DELIVERY_LEDGER_DUPLICATE"):
        module.commit_ledger(ledger, duplicate)


def test_claim_is_exclusive_and_commit_is_atomic(tmp_path):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    module.initialize_ledger(ledger, baseline())

    with module.ledger_claim(ledger):
        with pytest.raises(module.LedgerFailure, match="DELIVERY_LEDGER_BUSY"):
            with module.ledger_claim(ledger):
                pass
    module.commit_ledger(ledger, committed_record())

    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert data["entries"] == [committed_record()]
    assert data["committed"] == []
    assert not (tmp_path / ".ledger.json.claim").exists()
    assert not (tmp_path / ".ledger.json.tmp").exists()


def test_public_commit_serializes_two_distinct_writers_without_lost_update(tmp_path, monkeypatch):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    module.initialize_ledger(ledger, baseline())
    second = committed_record(
        work_key="1905:film:2259172",
        source_bundle_sha256="d" * 64,
        article_content_sha256="e" * 64,
        source_packet_sha256="f" * 64,
    )

    errors = synchronized_commits(module, ledger, [committed_record(), second])

    assert errors == []
    assert {entry["work_key"] for entry in module.load_ledger(ledger)["entries"]} == {
        "1905:film:2258538",
        "1905:film:2259172",
    }


def test_public_commit_serializes_duplicate_race_with_one_rejection(tmp_path, monkeypatch):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    module.initialize_ledger(ledger, baseline())

    errors = synchronized_commits(module, ledger, [committed_record(), committed_record()])

    assert len(errors) == 1
    assert str(errors[0]) == "DELIVERY_LEDGER_DUPLICATE_WORK_KEY"
    assert module.load_ledger(ledger)["entries"] == [committed_record()]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"baseline": {}}),
        lambda value: value["baseline"].pop("scope"),
        lambda value: value["baseline"].update({"unexpected": "value"}),
        lambda value: value["baseline"].update({"historical_delivery_ledger": "verified"}),
        lambda value: value["baseline"].update({"scope": "historical"}),
        lambda value: value["baseline"].update({"created_at": "not-a-timestamp"}),
        lambda value: value["baseline"].update({"source_repair_artifact": "elsewhere"}),
    ],
)
def test_commit_fails_closed_for_each_invalid_baseline_without_writing(tmp_path, mutation):
    module = load_module()
    ledger = tmp_path / "ledger.json"
    module.initialize_ledger(ledger, baseline())
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    mutation(payload)
    ledger.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = ledger.read_bytes()

    with pytest.raises(module.LedgerFailure, match="DELIVERY_LEDGER_BASELINE_INVALID"):
        module.commit_ledger(ledger, committed_record())

    assert ledger.read_bytes() == before


def test_initialized_ledger_is_consumed_by_orchestrator_and_retains_baseline(tmp_path):
    ledger_module = load_module()
    orchestrator = load_orchestrator()
    ledger = tmp_path / "ledger.json"
    ledger_module.initialize_ledger(ledger, baseline())
    bundle = {
        "bundle_id": "bundle-one",
        "bundle_sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "created_at": "2026-07-21T08:50:00Z",
        "work_identities": ["1905:film:2258538", "1905:film:2259172", "1905:film:2259123"],
    }
    article_hashes = {"A": "c" * 64, "B": "d" * 64, "C": "e" * 64}

    assert orchestrator.load_ledger(ledger) == []
    with orchestrator.ledger_claim(ledger):
        orchestrator.commit_ledger(ledger, bundle, article_hashes)

    persisted = json.loads(ledger.read_text(encoding="utf-8"))
    assert persisted["baseline"] == baseline()
    assert persisted["entries"] == []
    assert len(persisted["committed"]) == 1
    committed = orchestrator.load_ledger(ledger)
    with pytest.raises(orchestrator.RunFailure, match="DELIVERY_LEDGER_WORK_IDENTITY_REUSED"):
        orchestrator.reject_previously_delivered({**bundle, "bundle_id": "new", "bundle_sha256": "f" * 64, "content_sha256": "0" * 64}, committed)
    with pytest.raises(orchestrator.RunFailure, match="DELIVERY_LEDGER_BUNDLE_REUSED"):
        orchestrator.reject_previously_delivered({**bundle, "bundle_id": "new", "work_identities": ["1905:film:1", "1905:film:2", "1905:film:3"]}, committed)
    with pytest.raises(orchestrator.RunFailure, match="DELIVERY_LEDGER_ARTICLE_HASH_REUSED"):
        orchestrator.reject_article_delivery_hashes({"A": "c" * 64}, committed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"schema": "daily3-forward-delivery-ledger/v2"}),
        lambda value: value.pop("schema"),
        lambda value: value.update({"unexpected": "value"}),
        lambda value: value.update({"baseline": {}}),
        lambda value: value["baseline"].pop("scope"),
        lambda value: value["baseline"].update({"unexpected": "value"}),
        lambda value: value["baseline"].update({"historical_delivery_ledger": "verified"}),
        lambda value: value["baseline"].update({"scope": "historical"}),
        lambda value: value["baseline"].update({"created_at": "not-a-timestamp"}),
        lambda value: value["baseline"].update({"source_repair_artifact": "elsewhere"}),
    ],
)
def test_orchestrator_rejects_every_tampered_initialized_forward_ledger_without_writing(tmp_path, mutation):
    ledger_module = load_module()
    orchestrator = load_orchestrator()
    ledger = tmp_path / "ledger.json"
    ledger_module.initialize_ledger(ledger, baseline())
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    mutation(payload)
    ledger.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = ledger.read_bytes()
    bundle = {
        "bundle_id": "bundle-one",
        "bundle_sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "created_at": "2026-07-21T08:50:00Z",
        "work_identities": ["1905:film:2258538", "1905:film:2259172", "1905:film:2259123"],
    }

    with pytest.raises(orchestrator.RunFailure, match="DELIVERY_LEDGER_INVALID"):
        with orchestrator.ledger_claim(ledger):
            orchestrator.commit_ledger(ledger, bundle, {"A": "c" * 64, "B": "d" * 64, "C": "e" * 64})

    assert ledger.read_bytes() == before


def test_today_input_manifest_binds_approved_bundle_without_claiming_delivery(tmp_path):
    module = load_module()
    ledger = tmp_path / "delivery-ledger.json"
    manifest = tmp_path / "today-production-input-manifest.json"

    module.initialize_today_ledger_and_manifest(SOURCE_ROOT, ledger, manifest, "2026-07-21T08:50:00Z")

    result = json.loads(manifest.read_text(encoding="utf-8"))
    source_bundle = SOURCE_ROOT / "source-bundle-candidate.json"
    assert result["source_bundle"]["bundle_id"] == "daily3-today-source-bundle-repair-t_e67ffacb"
    assert result["source_bundle"]["sha256"] == digest(source_bundle)
    assert result["work_keys"] == ["1905:film:2258538", "1905:film:2259172", "1905:film:2259123"]
    assert set(result["source_packet_sha256"]) == set(result["work_keys"])
    assert result["created_at"] == "2026-07-21T08:50:00Z"
    assert result["historical_delivery_ledger"] == "NOT_FOUND_AND_UNVERIFIABLE"
    assert result["delivery_status"] == "registered_input_only_not_delivered"
    assert result["publication_authorized"] is False
    assert result["publication_performed"] is False
    assert json.loads(ledger.read_text(encoding="utf-8"))["entries"] == []


def test_today_input_manifest_fails_closed_when_preserved_raw_packet_hash_disagrees(tmp_path):
    module = load_module()
    source_root = tmp_path / "source-repair"
    shutil.copytree(SOURCE_ROOT, source_root)
    (source_root / "raw-packets" / "2258538.json").write_text("{}", encoding="utf-8")

    with pytest.raises(module.LedgerFailure, match="TODAY_SOURCE_INPUT_INVALID"):
        module.initialize_today_ledger_and_manifest(
            source_root,
            tmp_path / "delivery-ledger.json",
            tmp_path / "today-production-input-manifest.json",
            "2026-07-21T08:50:00Z",
        )
