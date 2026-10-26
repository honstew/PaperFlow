from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
KNOWN_MODELS = ("deepseek-flash", "deepseek-v4-pro")
SETTINGS_VERSION = 1


class AppSettings(BaseModel):
    """Non-secret application settings.

    The API key is deliberately absent: it lives in Windows Credential
    Manager through :class:`paperflow.core.secrets.SecretStore`.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = SETTINGS_VERSION
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: int = Field(default=120, ge=5, le=600)
    proxy: str = ""
    xelatex_path: str = ""
    remember_api_key: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是 http:// 或 https:// 开头的有效地址")
        if value.endswith("/chat/completions"):
            raise ValueError("Base URL 不应包含 /chat/completions，只填写服务根地址")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模型名称不能为空")
        return value

    @field_validator("proxy")
    @classmethod
    def validate_proxy(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("代理必须是 http:// 或 https:// 开头的地址")
        return value

    @field_validator("xelatex_path")
    @classmethod
    def normalize_xelatex_path(cls, value: str) -> str:
        return value.strip()


class SettingsStore:
    """Atomic JSON store for non-secret settings."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings.json 根节点必须是对象")
            return AppSettings.model_validate(data)
        except Exception:
            logger.exception("Failed to read settings from %s; using defaults", self.path)
            self._quarantine_broken_file()
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n"
        temp_path = self.path.with_suffix(".json.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, self.path)

    def _quarantine_broken_file(self) -> None:
        try:
            if self.path.exists():
                broken = self.path.with_suffix(".broken.json")
                if broken.exists():
                    broken.unlink()
                self.path.replace(broken)
        except OSError:
            logger.exception("Could not quarantine broken settings file")


def settings_as_dict(settings: AppSettings) -> dict[str, Any]:
    """Public settings dictionary, useful for diagnostics without secrets."""
    return settings.model_dump()