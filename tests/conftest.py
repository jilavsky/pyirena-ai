"""Shared pytest fixtures.

The bridge tests need a real NXcanSAS HDF5. We point at pyirena's test
data folder when present; on CI the folder isn't shipped, so those tests
auto-skip via the `requires_pyirena_testdata` marker.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

PYIRENA_TEST_H5_CANDIDATES = [
    Path(os.environ.get("PYIRENA_AI_TEST_H5", "")),
    Path.home() / "GitHub" / "pyirena" / "testData" / "TestUnifiedFit.h5",
    Path.home() / "GitHub" / "pyirena" / "testData" / "ProperNxcanSASNexus.h5",
    Path.home() / "GitHub" / "pyirena" / "testData" / "complexUnified.h5",
]


@pytest.fixture(scope="session")
def test_h5_path() -> Path:
    for p in PYIRENA_TEST_H5_CANDIDATES:
        if p and p.is_file():
            return p
    pytest.skip(
        "No pyirena NXcanSAS test file found. Set PYIRENA_AI_TEST_H5 "
        "to a NXcanSAS HDF5 path to enable these tests."
    )
