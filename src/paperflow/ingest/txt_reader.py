from __future__ import annotations

import logging
from pathlib import Path

from paperflow.core.document import (
    Document,
    Figure,
    ImportResult,
    ImportSummary,
    ParseWarning,
    Table,
)
from paperflow.core.project import ProjectWorkspace
from paperflow.ingest.common import (
    add_warning,
    classify_text_line,
    decode_text,
    detect_title,
    figure_from_caption,
    make_block,
    source_ref,
    table_from_caption,
)

logger = logging.getLogger(__name__)


def read_txt(
    source_file: Path,
    *,
    source_dir: Path,
    workspace: ProjectWorkspace,
) -> ImportResult:
    data = source_file.read_bytes()
    text, encoding = decode_text(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    blocks = []
    figures: list[Figure] = []
    tables: list[Table] = []
    warnings: list[ParseWarning] = []
    block_index = 0
    figure_index = 0
    table_index = 0
    pending_table: Table | None = None
    previous_block_id: str | None = None

    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        paragraph_lines = [lines[i].rstrip()]
        i += 1
        while i < len(lines) and lines[i].strip():
            paragraph_lines.append(lines[i].rstrip())
            i += 1
        raw_text = "\n".join(paragraph_lines).strip()
        line_start = start + 1
        line_end = i

        block_index += 1
        source = source_ref(
            source_file.name,
            format_name="txt",
            line_start=line_start,
            line_end=line_end,
            block_index=block_index,
        )

        tsv_rows = _parse_tsv(paragraph_lines)
        if tsv_rows and pending_table is not None:
            pending_table.rows = tsv_rows
            pending_table.status = "ready"
            pending_table.warnings.clear()
            block = make_block(
                block_index,
                kind="table",
                text="\n".join("\t".join(row) for row in tsv_rows),
                source=source,
                asset_id=pending_table.id,
            )
            blocks.append(block)
            previous_block_id = block.id
            pending_table = None
            continue

        kind, level, cleaned = classify_text_line(raw_text) if len(paragraph_lines) == 1 else (
            "paragraph",
            None,
            raw_text,
        )
        block = make_block(
            block_index,
            kind=kind,
            text=cleaned,
            source=source,
            heading_level=level,
        )

        if kind == "figure_caption":
            figure_index += 1
            figure = figure_from_caption(
                cleaned,
                figure_id=f"fig_{figure_index:03d}",
                anchor_after_block=previous_block_id,
                source_dir=source_dir,
                workspace=workspace,
                image_ref="",
                alt="",
            )
            figures.append(figure)
            block.asset_id = figure.id
            add_warning(
                warnings,
                "missing_figure",
                f"{figure.label or '图'} 尚未提供图片素材",
                block_id=block.id,
            )
        elif kind == "table_caption":
            table_index += 1
            table = table_from_caption(
                cleaned,
                table_id=f"tab_{table_index:03d}",
                anchor_after_block=previous_block_id,
            )
            tables.append(table)
            block.asset_id = table.id
            pending_table = table
        elif kind == "abstract" or kind == "keywords":
            # Keep these as dedicated blocks for M3's structure detection.
            pass

        blocks.append(block)
        previous_block_id = block.id

    if pending_table is not None:
        add_warning(
            warnings,
            "missing_table_data",
            f"{pending_table.label or '表'} 有题注但没有可识别的表格数据",
            block_id=None,
        )

    numeric_tables = [block for block in blocks if block.kind == "table"]
    if not numeric_tables and tables:
        add_warning(
            warnings,
            "table_data_manual",
            "检测到表格题注但没有可识别的表格数据，请在图表管理中补充",
        )

    document = Document(
        title=detect_title(blocks),
        format="txt",
        encoding=encoding,
        source_name=source_file.name,
        source_file=workspace.source_file,
        blocks=blocks,
        figures=figures,
        tables=tables,
        warnings=warnings,
    )
    summary = _summary(document, source_file.name, "TXT", encoding)
    return ImportResult(
        document=document,
        summary=summary,
        project_dir=str(workspace.root),
        source_copy=workspace.source_file,
    )


def _parse_tsv(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if "\t" not in line:
            return []
        cells = [cell.strip() for cell in line.split("\t")]
        if len(cells) < 2:
            return []
        rows.append(cells)
    return rows if len(rows) >= 2 else []


def _summary(document: Document, source_name: str, format_name: str, encoding: str) -> ImportSummary:
    return ImportSummary(
        source_name=source_name,
        format=format_name,
        encoding=encoding,
        block_count=len(document.blocks),
        heading_count=sum(1 for block in document.blocks if block.kind == "heading"),
        figure_count=len(document.figures),
        table_count=len(document.tables),
        warning_count=len(document.warnings),
    )