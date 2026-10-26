from __future__ import annotations

from paperflow.core.secrets import MemorySecretBackend, SecretStore, mask_key


class FailingBackend:
    def get_password(self, service_name: str, username: str) -> str | None:
        raise RuntimeError("backend unavailable")

    def set_password(self, service_name: str, username: str, password: str) -> None:
        raise RuntimeError("backend unavailable")

    def delete_password(self, service_name: str, username: str) -> None:
        raise RuntimeError("backend unavailable")


def test_memory_backend_round_trip() -> None:
    backend = MemorySecretBackend()
    store = SecretStore(backend=backend)
    assert store.set_key("sk-test-123456789") is True
    assert store.get_key() == "sk-test-123456789"
    assert store.backend_available is True
    assert store.delete_key() is True
    assert store.get_key() is None


def test_backend_failure_falls_back_to_memory() -> None:
    store = SecretStore(backend=FailingBackend())
    assert store.set_key("sk-test-123456789") is False
    assert store.get_key() == "sk-test-123456789"
    assert store.backend_available is False
    assert "backend unavailable" in store.last_error


def test_mask_key_never_reveals_full_key() -> None:
    masked = mask_key("sk-abcdefghijklmnop")
    assert masked.startswith("sk-a")
    assert masked.endswith("mnop")
    assert "abcdefghijkl" not in masked