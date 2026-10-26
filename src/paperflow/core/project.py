from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paperflow.core.document import Document, ImportResult, ImportSummary
from paperflow.core.fixes import RenderOverrides
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import M4State, build_m4_state
from paperflow.core.references import ReferenceState, parse_references
from paperflow.core.structure import StructureResult

logger = logging.getLogger(__name__)

_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_-]+")


@dataclass(slots=True)
class ProjectWorkspace:
    root: Path
    source_path: Path
    figures_dir: Path
    tables_dir: Path
    content_dir: Path

    @property
    def source_file(self) -> str:
        return str(self.source_path.relative_to(self.root)).replace("\\", "/")

    def relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root.resolve())).replace("\\", "/")

    def save_document(self, document: Document) -> Path:
        target = self.content_dir / "manuscript.json"
        _atomic_write(target, document.to_json() + "\n")
        return target

    def save_import_result(self, result: ImportResult) -> Path:
        target = self.content_dir / "import-result.json"
        _atomic_write(target, result.model_dump_json(indent=2) + "\n")
        return target

    def write_project_meta(self, *, source_name: str, format_name: str) -> None:
        payload = {
            "schema_version": 1,
            "source_name": source_name,
            "format": format_name,
            "created_at": datetime.now().astimezone().isoformat(),
        }
        _atomic_write(
            self.root / "project.json",
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )


def create_workspace(projects_dir: Path, source_path: Path) -> ProjectWorkspace:
    projects_dir.mkdir(parents=True, exist_ok=True)
    stem = _UNSAFE_NAME.sub("_", source_path.stem).strip("_")[:48] or "paper"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = projects_dir / f"{timestamp}-{stem}-{uuid.uuid4().hex[:4]}"
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "figures").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "tables").mkdir(parents=True, exist_ok=True)
    (root / "content").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "build").mkdir(parents=True, exist_ok=True)

    target = root / "source" / source_path.name
    shutil.copy2(source_path, target)
    logger.info("Created project workspace: %s", root)
    return ProjectWorkspace(
        root=root,
        source_path=target,
        figures_dir=root / "assets" / "figures",
        tables_dir=root / "assets" / "tables",
        content_dir=root / "content",
    )


class ProjectLoadError(RuntimeError):
    """Project cannot be reopened because required files are missing."""


@dataclass(slots=True)
class LoadedProject:
    root: Path
    imported: ImportResult
    structure: StructureResult | None = None
    m4: M4State | None = None
    references: ReferenceState | None = None
    layout: LayoutSettings | None = None
    overrides: RenderOverrides | None = None


def load_project(root: Path) -> LoadedProject:
    root = root.resolve()
    content = root / "content"
    if not content.is_dir():
        raise ProjectLoadError(f"项目缺少 content 目录：{root}")
    imported = _load_import_result(root)
    structure = _read_model(content / "structure.json", StructureResult)
    m4 = _read_model(content / "m4-state.json", M4State)
    if m4 is None and structure is not None:
        m4 = build_m4_state(imported, structure)
    references = _read_model(content / "references.json", ReferenceState)
    if references is None and structure is not None:
        references = parse_references(structure.document, structure)
    layout = _read_model(content / "layout.json", LayoutSettings)
    overrides = _read_model(content / "overrides.json", RenderOverrides)
    return LoadedProject(
        root=root,
        imported=imported,
        structure=structure,
        m4=m4,
        references=references,
        layout=layout,
        overrides=overrides,
    )


def _load_import_result(root: Path) -> ImportResult:
    content = root / "content"
    import_file = content / "import-result.json"
    if import_file.is_file():
        try:
            result = ImportResult.model_validate_json(
                import_file.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ProjectLoadError(f"无法读取导入结果：{exc}") from exc
        result.project_dir = str(root)
        if result.source_copy:
            result.source_copy = str(root / result.source_copy)
        return result
    manuscript_file = content / "manuscript.json"
    if not manuscript_file.is_file():
        raise ProjectLoadError("项目缺少 content/import-result.json 与 manuscript.json")
    try:
        document = Document.model_validate_json(
            manuscript_file.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise ProjectLoadError(f"无法读取 manuscript.json：{exc}") from exc
    summary = ImportSummary(
        source_name=document.source_name,
        format=document.format,
        encoding=document.encoding,
        block_count=len(document.blocks),
        heading_count=sum(1 for block in document.blocks if block.kind == "heading"),
        figure_count=len(document.figures),
        table_count=len(document.tables),
        warning_count=len(document.warnings),
    )
    source_copy = str(root / document.source_file) if document.source_file else ""
    return ImportResult(
        document=document,
        summary=summary,
        project_dir=str(root),
        source_copy=source_copy,
    )


def _read_model(path: Path, model_type):
    if not path.is_file():
        return None
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Cannot load %s: %s", path, exc)
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)