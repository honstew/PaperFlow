from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PAPERFLOW_HOME", tempfile.mkdtemp(prefix="paperflow-tests-"))

import pytest

from paperflow.core.secrets import MemorySecretBackend, SecretStore


@pytest.fixture
def secret_store() -> SecretStore:
    return SecretStore(backend=MemorySecretBackend())


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir()
    return path