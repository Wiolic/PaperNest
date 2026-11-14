from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SMALL = FIXTURES / "library_small"


@pytest.fixture
def small_lib_path(tmp_path: Path) -> Path:
    """样例库的可写副本。"""
    dest = tmp_path / "lib"
    shutil.copytree(SMALL, dest)
    return dest
