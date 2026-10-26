from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from paperflow.core.config import SettingsStore
from paperflow.core.secrets import default_secret_store
from paperflow.logging_setup import setup_logging
from paperflow.paths import get_app_paths
from paperflow.ui.main_window import MainWindow
from paperflow.ui.theme import apply_theme

logger = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    debug = "--debug" in argv
    paths = get_app_paths()
    paths.ensure()
    log_file = setup_logging(paths.log_dir, debug=debug)
    logger.info("PaperFlow starting; config=%s log=%s", paths.home, log_file)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName("PaperFlow")
    app.setApplicationDisplayName("PaperFlow · 智能论文排版")
    app.setOrganizationName("PaperFlow")
    apply_theme(app)

    settings_store = SettingsStore(paths.settings_file)
    settings = settings_store.load()
    secret_store = default_secret_store()

    window = MainWindow(
        settings,
        settings_store,
        secret_store,
        log_dir=paths.log_dir,
        projects_dir=paths.projects_dir,
        auto_detect="--no-auto-detect" not in argv,
    )
    window.show()
    if "--smoke-test" in argv:
        QTimer.singleShot(1800, window.close)
    try:
        return app.exec()
    except Exception:
        logger.exception("Unhandled UI error")
        QMessageBox.critical(
            None,
            "PaperFlow 遇到错误",
            f"程序遇到未处理的错误。日志位于：\n{log_file}",
        )
        return 1