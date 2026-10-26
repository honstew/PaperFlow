from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from paperflow.core.config import AppSettings, SettingsStore


def test_defaults_are_deepseek() -> None:
    settings = AppSettings()
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-flash"
    assert settings.timeout_s == 120
    assert settings.remember_api_key is True


def test_base_url_rejects_invalid_and_chat_endpoint() -> None:
    with pytest.raises(ValidationError):
        AppSettings(base_url="ftp://example.com")
    with pytest.raises(ValidationError):
        AppSettings(base_url="https://api.deepseek.com/chat/completions")


def test_settings_round_trip_has_no_api_key(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = AppSettings(base_url="https://example.com/v1", model="demo", proxy="")
    store.save(settings)

    raw = path.read_text(encoding="utf-8")
    assert "sk-" not in raw
    assert '"api_key"' not in raw
    loaded = store.load()
    assert loaded.base_url == "https://example.com/v1"
    assert loaded.model == "demo"


def test_broken_settings_are_quarantined(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.base_url == "https://api.deepseek.com"
    assert (tmp_path / "settings.broken.json").exists()


def test_json_payload_is_valid(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsStore(path).save(AppSettings())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["model"] == "deepseek-flash"
    assert "api_key" not in payload