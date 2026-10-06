"""Run the independent specification and proof mutation fixtures."""

import subprocess
import sys
from pathlib import Path


def test_validator_rejects_invalid_graph_and_proof():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_validator_behaviour.py")],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "61" in result.stdout
