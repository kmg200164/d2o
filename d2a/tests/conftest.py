import shutil
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def workspace_tmp():
    """Workspace-local temp path for Windows sandboxes that reject pytest's 0700 dirs."""
    parent = Path(__file__).resolve().parent / ".pytest-work"
    parent.mkdir(mode=0o777, exist_ok=True)
    path = parent / uuid4().hex
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            parent.rmdir()
        except OSError:
            pass
