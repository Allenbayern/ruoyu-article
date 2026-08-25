from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.codex_viral_research_package import main


def test_cli_help_is_available(capsys):
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    assert "capture-manifest" in capsys.readouterr().out


def test_direct_script_entrypoint_resolves_project_package():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "codex_viral_research_package.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "output-root" in result.stdout
