"""Runs scripts/check_contract.py so a drifting frontend/backend contract fails the test suite."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_contract.py"


def load_checker():
    """Import scripts/check_contract.py as a module (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("check_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontend_and_backend_agree():
    """Routes, field names, enums, form fields and env docs must match; no old API paths may remain."""
    if not SCRIPT.is_file():  # running from a backend-only copy
        return
    problems = load_checker().run()
    assert problems == [], "\n".join(problems)
