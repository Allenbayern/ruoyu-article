import importlib.util
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "graphite_minimal_external_adapter.py"
UPSTREAM_ROOT = Path(os.environ.get('GRAPHITE_UPSTREAM_ROOT', str(Path.home() / '.hermes' / 'graphite' / 'gzh-design-skill')))
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
    spec = importlib.util.spec_from_file_location("graphite_minimal_external_adapter", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture_content():
    return {
        "title": "合成样本标题",
        "introduction": "这是用于适配器测试的合成中文导语。",
        "sections": [
            {"heading": "第一节：样本结构", "paragraphs": ["第一段只描述合成样本。", "第二段用于验证叶子节点。"]},
            {"heading": "第二节：最小输出", "paragraphs": ["本段不包含外部事实或占位符。"]},
        ],
    }


def render(
    module,
    *,
    upstream_root=UPSTREAM_ROOT,
    expected_commit=EXPECTED_COMMIT,
    expected_validator_sha256=EXPECTED_VALIDATOR_SHA256,
):
    return module.render_graphite_minimal_external(
        mode="graphite_minimal_external",
        upstream_root=upstream_root,
        expected_commit=expected_commit,
        expected_validator_sha256=expected_validator_sha256,
        **fixture_content(),
    )


def validator_result(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["validator"], returncode, stdout, stderr)


def run_with_validator_result(monkeypatch, module, result=None, error=None):
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if str(command[1]).endswith("validate_gzh_html.py"):
            if error is not None:
                raise error
            return result
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fake_run)


def test_opt_in_adapter_renders_only_section_fragment_with_inline_styles_and_leaf_text():
    module = load_module()

    result = render(module)

    assert result["mode"] == "graphite_minimal_external"
    assert result["validator"]["validated"] is True
    assert result["validator"]["compatibility"] == "validator-backed only; no WeChat paste proof"
    html = result["html"]
    assert html.startswith("<section ")
    assert "<html" not in html.lower()
    assert "<head" not in html.lower()
    assert "<body" not in html.lower()
    assert "<script" not in html.lower()
    assert "<style" not in html.lower()
    assert "{{" not in html and "}}" not in html
    assert "style=" in html
    assert "合成样本标题" in html
    assert "这是用于适配器测试的合成中文导语。" in html
    assert "第一节：样本结构" in html
    assert "第一段只描述合成样本。" in html
    parser = TextLeafParser()
    parser.feed(html)
    assert parser.unwrapped_text == []


@pytest.mark.skipif(not (UPSTREAM_ROOT / ".git").is_dir(), reason="external validator checkout is absent")
def test_rendered_fragment_passes_exact_upstream_validator(tmp_path):
    module = load_module()
    result = render(module)
    output = tmp_path / "synthetic-fragment.html"
    output.write_text(result["html"], encoding="utf-8")

    validator = UPSTREAM_ROOT / "scripts" / "validate_gzh_html.py"
    completed = subprocess.run([sys.executable, str(validator), str(output)], text=True, capture_output=True, check=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ERROR" not in completed.stdout
    assert "WARNING" not in completed.stdout


def test_adapter_fails_closed_when_external_dependency_is_unavailable(tmp_path):
    module = load_module()

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_UNAVAILABLE"):
        render(module, upstream_root=tmp_path / "missing-checkout")


def test_adapter_fails_closed_when_external_commit_does_not_match():
    module = load_module()

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_DEPENDENCY_COMMIT_MISMATCH"):
        render(module, expected_commit="0" * 40)


def test_exact_approved_dependency_identity_passes():
    module = load_module()

    dependency = module.verify_external_validator(
        UPSTREAM_ROOT,
        EXPECTED_COMMIT,
        EXPECTED_VALIDATOR_SHA256,
    )

    assert dependency["upstream_root"] == str(UPSTREAM_ROOT.resolve())
    assert dependency["commit"] == EXPECTED_COMMIT
    assert dependency["validator_sha256"] == EXPECTED_VALIDATOR_SHA256


def test_adapter_rejects_dirty_or_stub_validator_hash_mismatch(tmp_path):
    module = load_module()
    stub_root = tmp_path / "gzh-design-skill"
    stub_validator = stub_root / "scripts" / "validate_gzh_html.py"
    stub_validator.parent.mkdir(parents=True)
    stub_validator.write_text("print('stub')\n", encoding="utf-8")

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_ROOT_MISMATCH"):
        module.verify_external_validator(stub_root, EXPECTED_COMMIT, EXPECTED_VALIDATOR_SHA256)


def test_adapter_rejects_dirty_validator_hash_mismatch(monkeypatch):
    module = load_module()

    class WrongHash:
        def hexdigest(self):
            return "0" * 64

    monkeypatch.setattr(module.hashlib, "sha256", lambda _: WrongHash())

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_DEPENDENCY_HASH_MISMATCH"):
        module.verify_external_validator(UPSTREAM_ROOT, EXPECTED_COMMIT, EXPECTED_VALIDATOR_SHA256)


def test_adapter_rejects_wrong_expected_validator_hash():
    module = load_module()

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_DEPENDENCY_HASH_MISMATCH"):
        render(module, expected_validator_sha256="0" * 64)


def test_adapter_rejects_wrong_validator_root_even_when_it_exists(tmp_path):
    module = load_module()
    other_root = tmp_path / "other-gzh-design-skill"
    other_root.mkdir()

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_ROOT_MISMATCH"):
        module.verify_external_validator(other_root, EXPECTED_COMMIT, EXPECTED_VALIDATOR_SHA256)


def test_adapter_rejects_wrong_validator_origin(monkeypatch):
    module = load_module()
    real_run_checked = module._run_checked

    def wrong_origin(command, failure_code):
        if command[-1] == "remote.origin.url":
            return "https://example.invalid/unapproved-validator.git"
        return real_run_checked(command, failure_code)

    monkeypatch.setattr(module, "_run_checked", wrong_origin)

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_ORIGIN_MISMATCH"):
        module.verify_external_validator(UPSTREAM_ROOT, EXPECTED_COMMIT, EXPECTED_VALIDATOR_SHA256)


def test_adapter_rejects_absent_validator_at_approved_root(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "VALIDATOR_RELATIVE_PATH", Path("scripts") / "missing_validator.py")

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_UNAVAILABLE"):
        module.verify_external_validator(UPSTREAM_ROOT, EXPECTED_COMMIT, EXPECTED_VALIDATOR_SHA256)


def test_adapter_rejects_nonzero_validator_return(monkeypatch):
    module = load_module()
    run_with_validator_result(monkeypatch, module, validator_result(returncode=1))

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_FAILED"):
        render(module)


@pytest.mark.parametrize("diagnostic", ["ERROR invalid HTML", "WARNING unsupported style"])
def test_adapter_rejects_validator_diagnostic_in_stdout(monkeypatch, diagnostic):
    module = load_module()
    run_with_validator_result(monkeypatch, module, validator_result(stdout=diagnostic))

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_FAILED"):
        render(module)


@pytest.mark.parametrize("diagnostic", ["ERROR invalid HTML", "WARNING unsupported style"])
def test_adapter_rejects_validator_diagnostic_in_stderr(monkeypatch, diagnostic):
    module = load_module()
    run_with_validator_result(monkeypatch, module, validator_result(stderr=diagnostic))

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_FAILED"):
        render(module)


def test_adapter_rejects_validator_invocation_failure(monkeypatch):
    module = load_module()
    run_with_validator_result(monkeypatch, module, error=OSError("validator unavailable"))

    with pytest.raises(module.ExternalValidatorError, match="EXTERNAL_VALIDATOR_FAILED"):
        render(module)


def test_adapter_rejects_non_opt_in_mode_before_rendering():
    module = load_module()

    with pytest.raises(module.AdapterInputError, match="UNSUPPORTED_RENDER_MODE"):
        module.render_graphite_minimal_external(
            mode="default",
            upstream_root=UPSTREAM_ROOT,
            expected_commit=EXPECTED_COMMIT,
            expected_validator_sha256=EXPECTED_VALIDATOR_SHA256,
            **fixture_content(),
        )
