"""Shared test fixtures for the media-intel-aios test suite."""

import os

import pytest


@pytest.fixture(autouse=True)
def _skip_stale_check_for_legacy_tests(monkeypatch):
    """Pre-existing tests exercise business logic against the real (stale)
    fixture file at tmp/daily-pipeline-discovery-verify-2026-06-15/. The
    Phase 2 staleness gate is tested separately in the negative-test block.
    """
    monkeypatch.setenv("MEDIA_INTEL_SKIP_STALE_CHECK", "1")
