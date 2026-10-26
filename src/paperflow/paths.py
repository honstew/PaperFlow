from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "PaperFlow"


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations owned by PaperFlow.

    ``PAPERFLOW_HOME`` is intentionally supported so development, tests and
    screenshots do not touch the real per-user configuration.
    """

    home: Path

    @property
    def settings_file(self) -> Path:
        return self.home / "settings.json"

    @property
    def log_dir(self) -> Path:
        return self.home / "logs"

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    def ensure(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)


def get_app_paths() -> AppPaths:
    configured = os.environ.get("PAPERFLOW_HOME", "").strip()
    if configured:
        return AppPaths(Path(configured).expanduser().resolve())
    return AppPaths(Path(user_config_dir(APP_NAME, appauthor=False)))