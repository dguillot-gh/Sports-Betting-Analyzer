"""Shared pytest configuration for backend tests.

Ensures the backend and backend/src directories are importable regardless of
how pytest is invoked (local, GitHub Actions, Docker).
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

for p in (str(BACKEND_ROOT), str(BACKEND_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


# The anyio pytest plugin can parametrize async tests over asyncio AND trio.
# trio is not a project dependency; pin to asyncio.
@pytest.fixture
def anyio_backend():
    return "asyncio"
