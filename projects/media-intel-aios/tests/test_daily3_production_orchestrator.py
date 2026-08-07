import importlib.util
import hashlib
import json
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "daily3_production_orchestrator.py"
FIXTURE = ROOT / "tmp" / "daily3-real-1905-20260718"
SOURCE_INPUT = FIXTURE / "source-input-draft.json"
SOURCE_RUN_ID = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))["run_id"]


def load_orchestrator():
    spec = importlib.util.spec_from_file_location("daily3_production_orchestrator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_subjects_accepts_1905_film_identity_namespace():
    module = load_orchestrator()

    subjects = module.source_subjects([
        "1905:film:2258538",
        "1905:film:2259172",
        "1905:film:2259123",
    ])

    assert subjects == ("2258538", "2259172", "2259123")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_source_bundle(source_input: Path, destination: Path, *, bundle_id: str) -> Path:
    source = json.loads(source_input.read_text(encoding="utf-8"))
    work_identities = [source["slots"][slot][0]["work_key"] for slot in ("A", "B", "C") if slot in source.get("slots", {}) and source["slots"][slot]]
    destination.write_text(
        json.dumps(
            {
                "bundle_id": bundle_id,
                "content_sha256": sha256(source_input),
                "created_at": "2026-07-20T00:00:00+00:00",
                "work_identities": work_identities,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return destination


def write_distinct_fixture(source_path: Path, raw_dir: Path) -> None:
    source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    identities = {"douban:37379599": "douban:47379599", "douban:37242440": "douban:47242440", "douban:36372941": "douban:46372941"}
    origins = {identity: f"1905-editorial-{identity.removeprefix('douban:')}-20260718" for identity in identities.values()}
    raw_dir.mkdir()
    for original in (FIXTURE / "raw-packets").glob("*.json"):
        old_identity = f"douban:{original.stem}"
        new_identity = identities[old_identity]
        (raw_dir / f"{new_identity.removeprefix('douban:')}.json").write_bytes(original.read_bytes())
    for atom in source["evidence_atoms"]:
        atom["work_key"] = identities[atom["work_key"]]
        atom["origin_packet_id"] = origins[atom["work_key"]]
        atom["origin_packet_sha256"] = sha256(raw_dir / f"{atom['work_key'].removeprefix('douban:')}.json")
    for slot in ("A", "B", "C"):
        draft = source["slots"][slot][0]
        draft["work_key"] = identities[draft["work_key"]]
        draft["origin_packet_id"] = origins[draft["work_key"]]
        draft["body"] += f"\n\n独立离线 fixture {slot}。"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")


def run_module(module, tmp_path: Path, *, run_id: str = SOURCE_RUN_ID, source_input: Path = SOURCE_INPUT):
    source_bundle = write_source_bundle(source_input, tmp_path / f"{run_id}.source-bundle.json", bundle_id=f"bundle-{run_id}")
    return module.run(
        Namespace(
            run_id=run_id,
            raw_dir=FIXTURE / "raw-packets",
            source_input=source_input,
            output_base=tmp_path,
            source_bundle=source_bundle,
            delivery_ledger=tmp_path / "delivery-ledger.json",
        )
    )


def write_renderer_double(path: Path, manifest_content: str, exit_code: int) -> None:
    path.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "output.mkdir(parents=True)\n"
        f"(output / 'manifest.json').write_text({manifest_content!r}, encoding='utf-8')\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )


def write_complete_renderer_double(path: Path, mutation: str = "") -> None:
    path.write_text(
        "from pathlib import Path\n"
        "import json, sys\n"
        "input_path = Path(sys.argv[sys.argv.index('--input') + 1])\n"
        "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
        "data = json.loads(input_path.read_text(encoding='utf-8'))\n"
        "output.mkdir(parents=True)\n"
        "slots = {}\n"
        "for slot in ('A', 'B', 'C'):\n"
        "    candidate = data['slots'][slot][0]\n"
        "    slot_dir = output / 'slots' / slot\n"
        "    slot_dir.mkdir(parents=True)\n"
        "    (slot_dir / 'article.html').write_text('<section><span>article</span></section>', encoding='utf-8')\n"
        "    (slot_dir / 'preview.html').write_text('<!doctype html><html><body><section><span>preview</span></section></body></html>', encoding='utf-8')\n"
        "    (slot_dir / 'evidence.json').write_text(json.dumps(candidate['evidence']), encoding='utf-8')\n"
        "    slots[slot] = {'candidate_id': candidate['id'], 'validator': {'kind': 'local_deterministic_preflight', 'validated': True}}\n"
        f"mutation = {mutation!r}\n"
        "if mutation == 'missing_article': (output / 'slots' / 'B' / 'article.html').unlink()\n"
        "if mutation == 'empty_html': (output / 'slots' / 'B' / 'article.html').write_text('', encoding='utf-8')\n"
        "if mutation == 'invalid_html': (output / 'slots' / 'B' / 'article.html').write_text('<div>bad</div>', encoding='utf-8')\n"
        "if mutation == 'malformed_html': (output / 'slots' / 'B' / 'article.html').write_text('<section><span>bad</section>', encoding='utf-8')\n"
        "if mutation == 'extra_slot': (output / 'slots' / 'D').mkdir()\n"
        "if mutation == 'absent_validator': del slots['B']['validator']\n"
        "if mutation == 'validator_returncode_failure': slots['B']['validator']['returncode'] = 1\n"
        "if mutation == 'validator_error': slots['B']['validator']['error'] = 'validator process failed'\n"
        "if mutation == 'validator_error_stderr': slots['B']['validator']['stderr'] = 'ERROR invalid HTML'\n"
        "if mutation == 'validator_error_diagnostics': slots['B']['validator']['diagnostics'] = 'ERROR invalid HTML'\n"
        "if mutation == 'mismatched_identity': slots['B']['candidate_id'] = 'wrong'\n"
        "manifest = {'run_id': data['run_id'], 'status': 'rendered_not_published', 'publication_authorized': False, 'publication_performed': False, 'validation': {'mode': 'local_deterministic_preflight'}, 'wechat_preview_verified': False, 'release_acceptance': {'status': 'not_accepted', 'reason': 'WECHAT_PREVIEW_UNVERIFIED'}, 'slots': slots}\n"
        "(output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )


def run_cli(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    arguments = list(extra)
    run_id = arguments[arguments.index("--run-id") + 1] if "--run-id" in arguments else SOURCE_RUN_ID
    source_input = Path(arguments[arguments.index("--source-input") + 1]) if "--source-input" in arguments else SOURCE_INPUT
    source_bundle = write_source_bundle(source_input, tmp_path / f"{run_id}.source-bundle.json", bundle_id=f"bundle-{run_id}")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-id",
            SOURCE_RUN_ID,
            "--raw-dir",
            str(FIXTURE / "raw-packets"),
            "--source-input",
            str(SOURCE_INPUT),
            "--output-base",
            str(tmp_path),
            "--source-bundle",
            str(source_bundle),
            "--delivery-ledger",
            str(tmp_path / "delivery-ledger.json"),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def failed_events(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "audit" / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def assert_failed_run_contract(run_dir: Path, failure_code: str) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failure_code"] == failure_code
    assert manifest["publication_authorized"] is False
    assert manifest["publication_performed"] is False
    assert manifest["delivery_candidate_created"] is False
    assert not (run_dir / "delivery").exists()
    assert failed_events(run_dir)[-1]["event"] == "run_failed"
    assert failed_events(run_dir)[-1]["failure_code"] == failure_code


def assert_delivery_contract_failure(
    tmp_path: Path,
    manifest_content: str,
    exit_code: int,
    failure_code: str = "DELIVERY_MANIFEST_INVALID",
) -> None:
    module = load_orchestrator()
    renderer = tmp_path / "renderer_double.py"
    write_renderer_double(renderer, manifest_content, exit_code)
    module.RENDERER = renderer

    status, manifest = run_module(module, tmp_path)

    assert status == 25
    run_dir = tmp_path / SOURCE_RUN_ID
    assert manifest["failure_code"] == failure_code
    assert_failed_run_contract(run_dir, failure_code)


def test_offline_real_three_slot_run_writes_auditable_nonpublishing_candidate(tmp_path):
    result = run_cli(tmp_path)

    assert result.returncode == 0, result.stderr
    run_dir = tmp_path / SOURCE_RUN_ID
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == SOURCE_RUN_ID
    assert manifest["source_packet_verified"] is True
    assert manifest["three_slot_structural_gate_passed"] is True
    assert manifest["delivery_html_validated"] is True
    assert manifest["publication_authorized"] is False
    assert manifest["publication_performed"] is False
    assert manifest["delivery_candidate_created"] is True
    assert manifest["source_bundle_verified"] is True
    assert manifest["delivery_ledger_committed"] is True
    assert set(manifest["raw_packet_sha256"]) == {"36372941", "37242440", "37379599"}
    assert manifest["release_acceptance"] == {
        "reason": "WECHAT_PREVIEW_UNVERIFIED",
        "status": "not_accepted",
    }
    assert json.loads((run_dir / "source-input.json").read_text(encoding="utf-8"))["run_id"] == SOURCE_RUN_ID
    assert json.loads((run_dir / "adapter-output.json").read_text(encoding="utf-8"))["run_id"] == SOURCE_RUN_ID
    assert json.loads((run_dir / "structural-gate" / "manifest.json").read_text(encoding="utf-8"))["run_id"] == SOURCE_RUN_ID
    assert json.loads((run_dir / "delivery" / "manifest.json").read_text(encoding="utf-8"))["run_id"] == SOURCE_RUN_ID
    events = failed_events(run_dir)
    assert [event["event"] for event in events] == [
        "run_started",
        "raw_packets_staged",
        "source_bundle_verified",
        "source_packet_verified",
        "adapter_completed",
        "three_slot_structural_gate_passed",
        "provenance_verified",
        "delivery_html_validated",
        "delivery_ledger_committed",
        "run_completed",
    ]
    assert all(event["run_id"] == manifest["run_id"] for event in events)


def test_real_orchestrator_positive_path_does_not_require_external_validator_arguments(tmp_path):
    source_bundle = write_source_bundle(SOURCE_INPUT, tmp_path / "source-bundle.json", bundle_id="bundle-no-external-validator")
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--run-id", SOURCE_RUN_ID,
            "--raw-dir", str(FIXTURE / "raw-packets"),
            "--source-input", str(SOURCE_INPUT),
            "--source-bundle", str(source_bundle),
            "--delivery-ledger", str(tmp_path / "delivery-ledger.json"),
            "--output-base", str(tmp_path / "runs"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    delivery = json.loads((tmp_path / "runs" / SOURCE_RUN_ID / "delivery" / "manifest.json").read_text(encoding="utf-8"))
    assert delivery["preflight"] == "local_deterministic_preflight"


def test_repeated_run_id_rejects_before_reusing_or_overwriting_prior_candidate(tmp_path):
    first = run_cli(tmp_path)
    run_dir = tmp_path / SOURCE_RUN_ID
    manifest_before = (run_dir / "manifest.json").read_bytes()
    events_before = (run_dir / "audit" / "events.jsonl").read_bytes()

    second = run_cli(tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 20
    assert "RUN_OUTPUT_ALREADY_EXISTS" in second.stderr
    assert (run_dir / "manifest.json").read_bytes() == manifest_before
    assert (run_dir / "audit" / "events.jsonl").read_bytes() == events_before
    assert (run_dir / "delivery" / "manifest.json").is_file()


def test_concurrent_same_run_id_has_one_owner_and_stable_loser_without_temp_residue(tmp_path):
    module = load_orchestrator()
    renderer = tmp_path / "renderer_double.py"
    write_complete_renderer_double(renderer)
    module.RENDERER = renderer
    outcomes = []
    start = threading.Barrier(2)

    def invoke():
        start.wait()
        try:
            outcomes.append(("result",) + run_module(module, tmp_path))
        except module.RunFailure as error:
            outcomes.append(("failure", error.code, error.exit_code))

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcome[-1] if outcome[0] == "failure" else outcome[1] for outcome in outcomes) == [0, 20]
    assert next(outcome for outcome in outcomes if outcome[0] == "failure")[1] == "RUN_OUTPUT_ALREADY_EXISTS"
    assert (tmp_path / SOURCE_RUN_ID / "manifest.json").is_file()
    assert list(tmp_path.glob(f".{SOURCE_RUN_ID}.*")) == []


def test_mkdtemp_initialization_failure_releases_claim_and_allows_same_run_id_retry(monkeypatch, tmp_path):
    module = load_orchestrator()
    renderer = tmp_path / "renderer_double.py"
    write_complete_renderer_double(renderer)
    module.RENDERER = renderer
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **_kwargs: (_ for _ in ()).throw(OSError("injected mkdtemp failure")))

    with __import__("pytest").raises(module.RunFailure, match="RUN_INITIALIZATION_FAILED") as captured:
        run_module(module, tmp_path)

    assert captured.value.exit_code == 20
    assert not (tmp_path / f".{SOURCE_RUN_ID}.claim").exists()
    assert list(tmp_path.glob(f".{SOURCE_RUN_ID}.tmp.*")) == []

    monkeypatch.undo()
    status, manifest = run_module(module, tmp_path)

    assert status == 0
    assert manifest["status"] == "completed_nonpublishing_candidate"


def test_non_oserror_initialization_failure_releases_claim_and_allows_same_run_id_retry(monkeypatch, tmp_path):
    module = load_orchestrator()
    renderer = tmp_path / "renderer_double.py"
    write_complete_renderer_double(renderer)
    module.RENDERER = renderer
    monkeypatch.setattr(
        module.tempfile,
        "mkdtemp",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("injected non-OSError initialization failure")),
    )

    with __import__("pytest").raises(module.RunFailure, match="RUN_INITIALIZATION_FAILED") as captured:
        run_module(module, tmp_path)

    assert captured.value.exit_code == 20
    assert not (tmp_path / f".{SOURCE_RUN_ID}.claim").exists()
    assert list(tmp_path.glob(f".{SOURCE_RUN_ID}.tmp.*")) == []

    monkeypatch.undo()
    status, manifest = run_module(module, tmp_path)

    assert status == 0
    assert manifest["status"] == "completed_nonpublishing_candidate"


def test_duplicate_work_fails_closed_without_delivery_candidate(tmp_path):
    source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    source["run_id"] = "duplicate-work"
    source["slots"]["B"][0]["factual_claims"] = [source["slots"]["A"][0]["factual_claims"][0]]
    bad_source = tmp_path / "duplicate-work.json"
    bad_source.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    result = run_cli(tmp_path, "--run-id", "duplicate-work", "--source-input", str(bad_source))

    assert result.returncode == 21
    assert_failed_run_contract(tmp_path / "duplicate-work", "SOURCE_PACKET_VERIFICATION_FAILED")


def test_missing_third_slot_fails_closed_without_historical_backfill(tmp_path):
    source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    source["run_id"] = "missing-third-slot"
    del source["slots"]["C"]
    bad_source = tmp_path / "missing-third-slot.json"
    bad_source.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    result = run_cli(tmp_path, "--run-id", "missing-third-slot", "--source-input", str(bad_source))

    assert result.returncode == 26
    assert_failed_run_contract(tmp_path / "missing-third-slot", "SOURCE_BUNDLE_WORK_IDENTITIES_INVALID")


def test_extra_raw_packet_fails_closed_before_adapter_or_delivery(tmp_path):
    raw_dir = tmp_path / "raw-packets"
    raw_dir.mkdir()
    for source in (FIXTURE / "raw-packets").glob("*.json"):
        (raw_dir / source.name).write_bytes(source.read_bytes())
    (raw_dir / "99999999.json").write_text("{}", encoding="utf-8")

    result = run_cli(tmp_path, "--run-id", SOURCE_RUN_ID, "--raw-dir", str(raw_dir))

    assert result.returncode == 21
    assert_failed_run_contract(tmp_path / SOURCE_RUN_ID, "RAW_PACKET_SET_NOT_EXACT_ALLOWLIST")


def test_raw_hash_mismatch_fails_closed_before_adapter_or_delivery(tmp_path):
    raw_dir = tmp_path / "raw-packets"
    raw_dir.mkdir()
    for source in (FIXTURE / "raw-packets").glob("*.json"):
        (raw_dir / source.name).write_bytes(source.read_bytes())
    changed = json.loads((raw_dir / "36372941.json").read_text(encoding="utf-8"))
    changed["evidence_atoms"][0]["claim"] += "（篡改）"
    (raw_dir / "36372941.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

    result = run_cli(tmp_path, "--raw-dir", str(raw_dir))

    assert result.returncode == 21
    assert_failed_run_contract(tmp_path / SOURCE_RUN_ID, "SOURCE_PACKET_VERIFICATION_FAILED")


def test_renderer_process_failure_fails_closed_without_delivery(tmp_path):
    module = load_orchestrator()
    renderer = tmp_path / "renderer_double.py"
    renderer.write_text("raise SystemExit(1)\n", encoding="utf-8")
    module.RENDERER = renderer

    status, manifest = run_module(module, tmp_path)

    assert status == 25
    assert manifest["failure_code"] == "DELIVERY_HTML_VALIDATION_FAILED"
    assert_failed_run_contract(tmp_path / SOURCE_RUN_ID, "DELIVERY_HTML_VALIDATION_FAILED")


def test_malformed_delivery_manifest_fails_closed_and_removes_delivery(tmp_path):
    assert_delivery_contract_failure(tmp_path, "not-json", 0)


def test_manifest_only_renderer_output_fails_closed_without_delivery_candidate(tmp_path):
    assert_delivery_contract_failure(
        tmp_path,
        json.dumps({
            "run_id": SOURCE_RUN_ID,
            "status": "rendered_not_published",
            "publication_authorized": False,
            "publication_performed": False,
            "release_acceptance": {"status": "not_accepted", "reason": "WECHAT_PREVIEW_UNVERIFIED"},
            "slots": {},
        }),
        2,
        "DELIVERY_ARTIFACT_INVALID",
    )


def test_incomplete_or_contradictory_renderer_artifacts_fail_closed(tmp_path):
    for mutation in (
        "missing_article",
        "empty_html",
        "invalid_html",
        "malformed_html",
        "extra_slot",
        "absent_validator",
        "validator_returncode_failure",
        "validator_error",
        "validator_error_stderr",
        "validator_error_diagnostics",
        "mismatched_identity",
    ):
        case = tmp_path / mutation
        case.mkdir()
        module = load_orchestrator()
        renderer = case / "renderer_double.py"
        write_complete_renderer_double(renderer, mutation)
        module.RENDERER = renderer

        status, manifest = run_module(module, case)

        assert status == 25
        assert manifest["failure_code"] == "DELIVERY_ARTIFACT_INVALID"
        assert_failed_run_contract(case / SOURCE_RUN_ID, "DELIVERY_ARTIFACT_INVALID")


def test_nonobject_delivery_manifest_fails_closed_and_removes_delivery(tmp_path):
    assert_delivery_contract_failure(tmp_path, "[]", 0)


def test_contradictory_delivery_publication_state_fails_closed(tmp_path):
    assert_delivery_contract_failure(
        tmp_path,
        json.dumps({
            "run_id": SOURCE_RUN_ID,
            "status": "rendered_not_published",
            "publication_authorized": True,
            "publication_performed": True,
            "release_acceptance": {"status": "not_accepted", "reason": "WECHAT_PREVIEW_UNVERIFIED"},
        }),
        2,
    )


def test_missing_delivery_publication_boolean_fails_closed(tmp_path):
    assert_delivery_contract_failure(
        tmp_path,
        json.dumps({
            "run_id": SOURCE_RUN_ID,
            "status": "rendered_not_published",
            "publication_authorized": False,
            "release_acceptance": {"status": "not_accepted", "reason": "WECHAT_PREVIEW_UNVERIFIED"},
        }),
        2,
    )


def test_exit_two_requires_not_accepted_wechat_preview_state(tmp_path):
    assert_delivery_contract_failure(
        tmp_path,
        json.dumps({
            "run_id": SOURCE_RUN_ID,
            "status": "rendered_not_published",
            "publication_authorized": False,
            "publication_performed": False,
            "release_acceptance": {"status": "accepted", "reason": "fake"},
        }),
        2,
    )


def test_renderer_exit_and_manifest_status_mismatch_fails_closed(tmp_path):
    assert_delivery_contract_failure(
        tmp_path,
        json.dumps({
            "run_id": SOURCE_RUN_ID,
            "status": "wrong-status",
            "publication_authorized": False,
            "publication_performed": False,
            "release_acceptance": {"status": "not_accepted", "reason": "WECHAT_PREVIEW_UNVERIFIED"},
        }),
        2,
    )


def test_source_run_id_mismatch_fails_closed_without_delivery(tmp_path):
    module = load_orchestrator()
    source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    source["run_id"] = "different-source-run"
    mismatched_source = tmp_path / "mismatched-source-input.json"
    mismatched_source.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")

    status, manifest = run_module(module, tmp_path, source_input=mismatched_source)

    assert status == 21
    assert manifest["failure_code"] == "SOURCE_RUN_ID_MISMATCH"
    assert manifest["delivery_candidate_created"] is False
    assert not (tmp_path / SOURCE_RUN_ID / "delivery").exists()


def test_two_explicit_fresh_source_bundles_commit_once_each_and_reuse_fails_closed(tmp_path):
    first_source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    first_source["run_id"] = "fresh-bundle-one"
    first_path = tmp_path / "fresh-one.json"
    first_path.write_text(json.dumps(first_source, ensure_ascii=False), encoding="utf-8")
    second_path = tmp_path / "fresh-two.json"
    second_raw = tmp_path / "fresh-two-raw"
    write_distinct_fixture(second_path, second_raw)
    second_source = json.loads(second_path.read_text(encoding="utf-8"))
    second_source["run_id"] = "fresh-bundle-two"
    second_path.write_text(json.dumps(second_source, ensure_ascii=False), encoding="utf-8")
    first_bundle = write_source_bundle(first_path, tmp_path / "bundle-one.json", bundle_id="manual-fixture-one")
    second_bundle = write_source_bundle(second_path, tmp_path / "bundle-two.json", bundle_id="manual-fixture-two")
    ledger = tmp_path / "delivery-ledger.json"

    first = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "fresh-bundle-one", "--raw-dir", str(FIXTURE / "raw-packets"), "--source-input", str(first_path), "--source-bundle", str(first_bundle), "--delivery-ledger", str(ledger), "--output-base", str(tmp_path / "runs")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    second = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "fresh-bundle-two", "--raw-dir", str(second_raw), "--source-input", str(second_path), "--source-bundle", str(second_bundle), "--delivery-ledger", str(ledger), "--output-base", str(tmp_path / "runs")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    reused = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "fresh-bundle-one", "--raw-dir", str(FIXTURE / "raw-packets"), "--source-input", str(first_path), "--source-bundle", str(first_bundle), "--delivery-ledger", str(ledger), "--output-base", str(tmp_path / "reused-runs")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert reused.returncode != 0
    rejected = tmp_path / "reused-runs" / "fresh-bundle-one"
    assert_failed_run_contract(rejected, "DELIVERY_LEDGER_BUNDLE_REUSED")
    committed = json.loads(ledger.read_text(encoding="utf-8"))["committed"]
    assert len(committed) == 2
    assert {item["bundle_id"] for item in committed} == {"manual-fixture-one", "manual-fixture-two"}


def test_ledger_rejections_leave_only_committed_entries_and_no_delivery_candidate(tmp_path):
    first_source = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    first_source["run_id"] = "ledger-baseline"
    first_path = tmp_path / "baseline.json"
    first_path.write_text(json.dumps(first_source, ensure_ascii=False), encoding="utf-8")
    first_bundle = write_source_bundle(first_path, tmp_path / "baseline-bundle.json", bundle_id="ledger-baseline")
    ledger = tmp_path / "delivery-ledger.json"
    baseline = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "ledger-baseline", "--raw-dir", str(FIXTURE / "raw-packets"), "--source-input", str(first_path), "--source-bundle", str(first_bundle), "--delivery-ledger", str(ledger), "--output-base", str(tmp_path / "runs")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    duplicate_work = json.loads(SOURCE_INPUT.read_text(encoding="utf-8"))
    duplicate_work["run_id"] = "ledger-duplicate-work"
    duplicate_path = tmp_path / "duplicate-work.json"
    duplicate_path.write_text(json.dumps(duplicate_work, ensure_ascii=False), encoding="utf-8")
    duplicate_bundle = write_source_bundle(duplicate_path, tmp_path / "duplicate-work-bundle.json", bundle_id="ledger-duplicate-work")
    rejected = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "ledger-duplicate-work", "--raw-dir", str(FIXTURE / "raw-packets"), "--source-input", str(duplicate_path), "--source-bundle", str(duplicate_bundle), "--delivery-ledger", str(ledger), "--output-base", str(tmp_path / "runs")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )

    assert baseline.returncode == 0, baseline.stderr
    assert rejected.returncode == 26
    assert_failed_run_contract(tmp_path / "runs" / "ledger-duplicate-work", "DELIVERY_LEDGER_WORK_IDENTITY_REUSED")
    assert len(json.loads(ledger.read_text(encoding="utf-8"))["committed"]) == 1
