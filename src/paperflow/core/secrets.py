from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

SERVICE_NAME = "PaperFlow"
ACCOUNT_NAME = "deepseek_api_key"


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class SecretStore:
    """Windows Credential Manager-backed API key storage.

    If the OS backend is unavailable, the key is kept in memory for the current
    session only.  It is never written to settings.json or logs.
    """

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend
        self._memory_key: str | None = None
        self._backend_ok: bool | None = None
        self._last_error = ""

    @property
    def backend_available(self) -> bool:
        return self._backend_ok is True

    @property
    def last_error(self) -> str:
        return self._last_error

    def get_key(self) -> str | None:
        if self._backend is None:
            return self._memory_key
        try:
            value = self._backend.get_password(SERVICE_NAME, ACCOUNT_NAME)
            self._backend_ok = True
            self._last_error = ""
            if value:
                self._memory_key = value
            return value
        except Exception as exc:  # keyring backends raise backend-specific errors
            self._backend_ok = False
            self._last_error = _safe_error(exc)
            logger.warning("Credential backend unavailable: %s", self._last_error)
            return self._memory_key

    def set_key(self, key: str) -> bool:
        key = key.strip()
        if not key:
            return False
        self._memory_key = key
        if self._backend is None:
            return False
        try:
            self._backend.set_password(SERVICE_NAME, ACCOUNT_NAME, key)
            self._backend_ok = True
            self._last_error = ""
            return True
        except Exception as exc:
            self._backend_ok = False
            self._last_error = _safe_error(exc)
            logger.warning("Could not save key to credential backend: %s", self._last_error)
            return False

    def delete_key(self) -> bool:
        self._memory_key = None
        if self._backend is None:
            return False
        try:
            self._backend.delete_password(SERVICE_NAME, ACCOUNT_NAME)
            self._backend_ok = True
            self._last_error = ""
            return True
        except Exception as exc:
            self._backend_ok = False
            self._last_error = _safe_error(exc)
            logger.warning("Could not delete key from credential backend: %s", self._last_error)
            return False


def _safe_error(exc: BaseException) -> str:
    # Never let a backend exception leak a key into the UI or log.
    text = str(exc).strip()
    return text[:240] if text else exc.__class__.__name__


class MemorySecretBackend:
    """Small test double; not used by the application."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


def mask_key(key: str) -> str:
    key = key.strip()
    if not key:
        return "未配置"
    if len(key) <= 10:
        return "已配置"
    return f"{key[:4]}…{key[-4:]}"


def default_secret_store() -> SecretStore:
    backend: KeyringBackend | None
    try:
        import keyring

        backend = keyring
    except Exception:  # pragma: no cover - import failure is environment-specific
        backend = None
    store = SecretStore(backend=backend)
    if backend is not None:
        store.get_key()
    return store


def make_store_for_tests(backend: Any | None = None) -> SecretStore:
    return SecretStore(backend=backend)