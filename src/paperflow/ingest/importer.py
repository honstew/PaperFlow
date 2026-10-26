from __future__ import annotations

import logging
from pathlib import Path

from paperflow.core.document import ImportResult
from paperflow.core.project import create_workspace
from paperflow.ingest.markdown_reader import read_markdown
from paperflow.ingest.txt_reader import read_txt

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
MAX_FILE_BYTES = 50 * 1024 * 1024


class IngestError(Exception):
    """Raised when a source document cannot be imported."""


def import_document(source_path: Path, *, projects_dir: Path) -> ImportResult:
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise IngestError(f"文件不存在：{source_path.name}")
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError("仅支持 .txt、.md、.markdown 文件；不支持 DOCX/DOC/PDF")
    size = source_path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise IngestError("文件超过 50 MB，首版不处理超大文档")
    if size == 0:
        raise IngestError("文件为空")

    workspace = create_workspace(projects_dir, source_path)
    source_copy = workspace.source_path
    try:
        if suffix == ".txt":
            result = read_txt(source_copy, source_dir=source_path.parent, workspace=workspace)
        else:
            result = read_markdown(source_copy, source_dir=source_path.parent, workspace=workspace)
        workspace.write_project_meta(
            source_name=source_path.name,
            format_name=result.document.format,
        )
        workspace.save_document(result.document)
        workspace.save_import_result(result)
    except Exception:
        logger.exception("Import failed for %s", source_path)
        raise
    logger.info(
        "Imported %s: %d blocks, %d figures, %d tables, %d warnings",
        source_path.name,
        result.summary.block_count,
        result.summary.figure_count,
        result.summary.table_count,
        result.summary.warning_count,
    )
    return result