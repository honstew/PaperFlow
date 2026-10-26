from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class RecentProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str
    title: str = ""
    source_name: str = ""
    format: str = ""
    updated_at: str = Field(
        default_factory=lambda: datetime.now().astimezone().isoformat()
    )


class RecentProjectsStore:
    def __init__(self, path: Path, *, limit: int = 10) -> None:
        self.path = path
        self.limit = limit

    def load(self) -> list[RecentProject]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Cannot read recent projects: %s", self.path)
            return []
        items = payload.get("projects", []) if isinstance(payload, dict) else []
        result: list[RecentProject] = []
        for item in items:
            try:
                result.append(RecentProject.model_validate(item))
            except Exception:
                continue
        return result[: self.limit]

    def add(self, root: Path, *, title: str, source_name: str, format_name: str) -> list[RecentProject]:
        root_text = str(root.resolve())
        items = [
            item
            for item in self.load()
            if Path(item.root).resolve() != Path(root_text)
        ]
        items.insert(
            0,
            RecentProject(
                root=root_text,
                title=title,
                source_name=source_name,
                format=format_name,
            ),
        )
        items = items[: self.limit]
        self._save(items)
        return items

    def remove(self, root: Path) -> list[RecentProject]:
        target = str(root.resolve())
        items = [
            item
            for item in self.load()
            if Path(item.root).resolve() != Path(target)
        ]
        self._save(items)
        return items

    def prune_missing(self) -> list[RecentProject]:
        items = [item for item in self.load() if Path(item.root).is_dir()]
        self._save(items)
        return items

    def _save(self, items: list[RecentProject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "projects": [item.model_dump() for item in items],
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)