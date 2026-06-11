import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A fresh workspace root for each test."""
    monkeypatch.setenv("RESYNTH_ROOT", str(tmp_path))
    return tmp_path
