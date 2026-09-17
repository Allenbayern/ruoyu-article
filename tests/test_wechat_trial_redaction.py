from __future__ import annotations

import importlib.util
from pathlib import Path


RUN_TRIAL_PATH = (
    Path(__file__).resolve().parents[1]
    / "runs"
    / "2026-08-22"
    / "wechat-free-trial-100"
    / "run_trial.py"
)


def load_run_trial():
    spec = importlib.util.spec_from_file_location("wechat_free_trial_run_trial", RUN_TRIAL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_trial = load_run_trial()


def test_generic_sensitive_query_keys_are_case_and_separator_insensitive():
    value = (
        "https://example.test/a?Access-Token=REDACTED_VALUE&CLIENT_SECRET=REDACTED_VALUE"
        "&x-signature=REDACTED_VALUE&keep=1"
    )
    assert run_trial.sanitize_sensitive_params(value) == "https://example.test/a?keep=1"


def test_common_credential_query_key_families_are_removed():
    value = (
        "https://example.test/a?api_key=REDACTED_VALUE&secret=REDACTED_VALUE"
        "&password=REDACTED_VALUE&authorization=REDACTED_VALUE&keep=1"
    )
    assert run_trial.sanitize_sensitive_params(value) == "https://example.test/a?keep=1"


def test_html_escaped_url_and_duplicate_sensitive_params_are_sanitized():
    value = (
        "See https://example.test/a?token=REDACTED_VALUE&amp;TOKEN=REDACTED_VALUE"
        "&amp;page=2."
    )
    assert run_trial.sanitize_sensitive_params(value) == "See https://example.test/a?page=2."


def test_multiple_urls_in_one_body_are_processed_independently():
    value = (
        "A https://example.test/a?sig=REDACTED_VALUE&keep=one and "
        "B https://example.test/b?article=two&auth_token=REDACTED_VALUE"
    )
    assert run_trial.sanitize_sensitive_params(value) == (
        "A https://example.test/a?keep=one and "
        "B https://example.test/b?article=two"
    )


def test_non_sensitive_non_wechat_query_is_preserved_byte_for_byte():
    value = "https://example.test/a?utm_source=feed&article_id=42&keep=x#section"
    assert run_trial.sanitize_sensitive_params(value) == value


def test_wechat_short_link_keeps_only_public_short_id():
    value = "https://mp.weixin.qq.com/s/Short_ID?token=REDACTED_VALUE&keep=1"
    assert run_trial.sanitize_sensitive_params(value) == "https://mp.weixin.qq.com/s/Short_ID"


def test_wechat_long_link_keeps_public_identity_fields_only():
    value = (
        "https://mp.weixin.qq.com/s?__biz=BIZ_VALUE&mid=123&idx=1&sn=SN_VALUE"
        "&pass_ticket=REDACTED_VALUE&token=REDACTED_VALUE"
    )
    assert run_trial.sanitize_sensitive_params(value) == (
        "https://mp.weixin.qq.com/s?__biz=BIZ_VALUE&mid=123&idx=1&sn=SN_VALUE"
    )


def test_unrecoverable_wechat_url_is_irreversibly_redacted():
    value = "https://mp.weixin.qq.com/s?__biz=BIZ_VALUE&mid=123&token=REDACTED_VALUE"
    cleaned = run_trial.sanitize_sensitive_params(value)
    assert cleaned == "[REDACTED]"
    assert "BIZ_VALUE" not in cleaned
    assert "REDACTED_VALUE" not in cleaned


def test_sanitization_is_idempotent():
    value = (
        "https://example.test/a?token=REDACTED_VALUE&keep=1 "
        "https://mp.weixin.qq.com/s?__biz=BIZ_VALUE&mid=123&idx=1&sn=SN_VALUE"
    )
    once = run_trial.sanitize_sensitive_params(value)
    assert run_trial.sanitize_sensitive_params(once) == once
