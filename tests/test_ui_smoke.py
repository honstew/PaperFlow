from __future__ import annotations

from pathlib import Path

from paperflow.core.config import AppSettings, SettingsStore
from paperflow.core.secrets import MemorySecretBackend, SecretStore
from paperflow.ingest import import_document
from paperflow.ui.main_window import MainWindow


def test_main_window_and_settings_save(qtbot, tmp_path: Path) -> None:
    settings_store = SettingsStore(tmp_path / "settings.json")
    secret_store = SecretStore(backend=MemorySecretBackend())
    window = MainWindow(
        AppSettings(),
        settings_store,
        secret_store,
        log_dir=tmp_path / "logs",
        projects_dir=tmp_path / "projects",
        auto_detect=False,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(50)

    assert len(window.nav_steps) == 8
    assert window.nav_steps["setup"].property("active") == "true"
    assert window.setup_page.env_report is None
    assert window.setup_page.connection is None

    window._on_nav_clicked("import")
    assert window.page_stack.currentWidget() is window.import_scroll
    assert window.nav_steps["import"].property("active") == "true"
    assert window.top_title.text() == "导入论文"

    window.setup_page.api_key_edit.setText("sk-test-ui-123456")
    window.setup_page.base_url_edit.setText("https://api.deepseek.com")
    window.setup_page.model_combo.setCurrentText("deepseek-flash")
    assert window.setup_page.persist_settings(notify=False) is True

    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "sk-test-ui-123456" not in raw
    assert secret_store.get_key() == "sk-test-ui-123456"

    window.close()


def test_invalid_base_url_is_rejected(qtbot, tmp_path: Path) -> None:
    window = MainWindow(
        AppSettings(),
        SettingsStore(tmp_path / "settings.json"),
        SecretStore(backend=MemorySecretBackend()),
        log_dir=tmp_path / "logs",
        projects_dir=tmp_path / "projects",
        auto_detect=False,
    )
    qtbot.addWidget(window)
    window.setup_page.base_url_edit.setText("not-a-url")
    assert window.setup_page.persist_settings(notify=False) is False
    assert window.setup_page.api_banner.property("state") == "error"
    window.close()


def test_session_only_key_is_not_persisted(qtbot, tmp_path: Path) -> None:
    secret_store = SecretStore(backend=MemorySecretBackend())
    window = MainWindow(
        AppSettings(),
        SettingsStore(tmp_path / "settings.json"),
        secret_store,
        log_dir=tmp_path / "logs",
        projects_dir=tmp_path / "projects",
        auto_detect=False,
    )
    qtbot.addWidget(window)
    window.setup_page.remember_check.setChecked(False)
    window.setup_page.api_key_edit.setText("sk-session-only-123")
    assert window.setup_page.persist_settings(notify=False) is True
    assert secret_store.get_key() is None
    assert window.setup_page.has_key is True
    window.close()


def test_structure_nav_is_enabled_after_import(qtbot, tmp_path: Path) -> None:
    window = MainWindow(
        AppSettings(),
        SettingsStore(tmp_path / "settings.json"),
        SecretStore(backend=MemorySecretBackend()),
        log_dir=tmp_path / "logs",
        projects_dir=tmp_path / "projects",
        auto_detect=False,
    )
    qtbot.addWidget(window)
    result = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    window._on_import_completed(result)

    assert window.nav_steps["structure"].isEnabled() is True
    assert window.nav_steps["assets"].isEnabled() is True
    assert window.nav_steps["metadata"].isEnabled() is True
    assert window.structure_page.block_table.rowCount() == 29
    assert window.structure_page.working_result is not None
    assert window._m4_state is not None
    assert window.assets_page.asset_list.count() == 2
    window.close()