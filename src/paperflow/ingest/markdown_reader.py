from __future__ import annotations

import logging
import re
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin

from paperflow.core.document import (
    Document,
    Figure,
    ImportResult,
    ImportSummary,
    ParseWarning,
    Run,
    SourceRef,
    Table,
)
from paperflow.core.project import ProjectWorkspace
from paperflow.ingest.common import (
    add_warning,
    caption_parts,
    classify_text_line,
    decode_text,
    detect_title,
    figure_from_caption,
    make_block,
    source_ref,
    table_from_caption,
)

logger = logging.getLogger(__name__)

_SPECIAL_TITLES = {"引言", "绪论", "摘要", "关键词", "参考文献", "致谢", "结论"}


def read_markdown(
    source_file: Path,
    *,
    source_dir: Path,
    workspace: ProjectWorkspace,
) -> ImportResult:
    data = source_file.read_bytes()
    text, encoding = decode_text(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    md = MarkdownIt("commonmark").enable("table").enable("strikethrough").use(dollarmath_plugin)
    tokens = md.parse(text)

    blocks = []
    figures: list[Figure] = []
    tables: list[Table] = []
    warnings: list[ParseWarning] = []
    block_index = 0
    figure_index = 0
    table_index = 0
    previous_block_id: str | None = None
    last_figure: Figure | None = None
    pending_table: Table | None = None
    title_candidate = ""

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.type == "heading_open":
            level = _heading_level(token.tag)
            inline = _next_inline(tokens, i)
            runs, images, inline_warnings = _parse_inline(
                inline,
                source_dir=source_dir,
                workspace=workspace,
            )
            text_value = _runs_text(runs).strip()
            block_index = len(blocks) + 1
            source = _source(source_file, token, "markdown", block_index, i + 1)
            block = make_block(
                block_index,
                kind="heading",
                text=text_value,
                heading_level=min(4, level),
                source=source,
                runs=runs,
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            if level == 1 and not title_candidate and text_value not in _SPECIAL_TITLES:
                title_candidate = text_value
            _add_inline_warnings(warnings, inline_warnings, block.id)
            _add_images(
                images,
                blocks=blocks,
                figures=figures,
                warnings=warnings,
                start_block_number=len(blocks) + 1,
                source=source,
                source_dir=source_dir,
                workspace=workspace,
                start_index=figure_index,
                anchor_after=block.id,
            )
            figure_index = len(figures)
            previous_block_id = blocks[-1].id
            last_figure = figures[-1] if images and figures else None
            i += 1
            continue

        if token.type == "paragraph_open":
            inline = _next_inline(tokens, i)
            runs, images, inline_warnings = _parse_inline(
                inline,
                source_dir=source_dir,
                workspace=workspace,
            )
            text_value = _runs_text(runs).strip()
            block_index = len(blocks) + 1
            source = _source(source_file, token, "markdown", block_index, i + 1)
            kind, level, cleaned = (
                classify_text_line(text_value)
                if text_value and "\n" not in text_value
                else ("paragraph", None, text_value)
            )

            if kind == "figure_caption":
                figure = _caption_figure(
                    text_value,
                    figure_index=figure_index + 1,
                    anchor_after_block=previous_block_id,
                    last_figure=last_figure,
                    source_dir=source_dir,
                    workspace=workspace,
                )
                if figure.id not in {item.id for item in figures}:
                    figures.append(figure)
                    figure_index += 1
                else:
                    figure_index = len(figures)
                block = make_block(
                    block_index,
                    kind="figure_caption",
                    text=cleaned,
                    source=source,
                    runs=runs,
                    asset_id=figure.id,
                )
                blocks.append(block)
                previous_block_id = block.id
                last_figure = figure
                if figure.status != "ready":
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
                pending_table = table
                block = make_block(
                    block_index,
                    kind="table_caption",
                    text=cleaned,
                    source=source,
                    runs=runs,
                    asset_id=table.id,
                )
                blocks.append(block)
                previous_block_id = block.id
                last_figure = None
            elif images and not text_value:
                if images:
                    _add_images(
                        images,
                        blocks=blocks,
                        figures=figures,
                        warnings=warnings,
                        start_block_number=len(blocks) + 1,
                        source=source,
                        source_dir=source_dir,
                        workspace=workspace,
                        start_index=figure_index,
                        anchor_after=previous_block_id,
                    )
                    figure_index = len(figures)
                    previous_block_id = blocks[-1].id
                    last_figure = figures[-1] if figures else None
                else:
                    block = make_block(
                        block_index,
                        kind="paragraph",
                        text="",
                        source=source,
                        runs=runs,
                    )
                    blocks.append(block)
                    previous_block_id = block.id
            else:
                block = make_block(
                    block_index,
                    kind=kind,
                    text=cleaned,
                    heading_level=level,
                    source=source,
                    runs=runs,
                )
                blocks.append(block)
                previous_block_id = block.id
                _add_inline_warnings(warnings, inline_warnings, block.id)
                if images:
                    _add_images(
                        images,
                        blocks=blocks,
                        figures=figures,
                        warnings=warnings,
                        start_block_number=len(blocks) + 1,
                        source=source,
                        source_dir=source_dir,
                        workspace=workspace,
                        start_index=figure_index,
                        anchor_after=block.id,
                    )
                    figure_index = len(figures)
                    previous_block_id = blocks[-1].id
                    last_figure = figures[-1] if figures else None
                else:
                    last_figure = None
            i += 1
            continue

        if token.type in {"fence", "code_block"}:
            block_index = len(blocks) + 1
            block = make_block(
                block_index,
                kind="code",
                text=token.content.rstrip("\n"),
                source=_source(source_file, token, "markdown", block_index, i + 1),
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i += 1
            continue

        if token.type == "table_open":
            rows, header_rows, next_index = _consume_table(tokens, i)
            table_index += 1
            if pending_table is None:
                table = Table(
                    id=f"tab_{table_index:03d}",
                    label=f"表{table_index}",
                    caption="",
                    rows=rows,
                    header_rows=header_rows,
                    anchor_after_block=previous_block_id,
                    status="ready" if rows else "pending",
                )
                tables.append(table)
                add_warning(
                    warnings,
                    "table_missing_caption",
                    f"表{table_index} 缺少题注，请在图表管理中补充",
                )
            else:
                table = pending_table
                table.rows = rows
                table.header_rows = header_rows
                table.status = "ready" if rows else "pending"
                table.warnings.clear()
                pending_table = None
            if not rows:
                add_warning(warnings, "table_empty", f"{table.label} 没有可识别的单元格")
            block_index = len(blocks) + 1
            block = make_block(
                block_index,
                kind="table",
                text=table.caption or table.label,
                source=_source(source_file, token, "markdown", block_index, i + 1),
                asset_id=table.id,
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i = next_index
            continue

        if token.type in {"bullet_list_open", "ordered_list_open"}:
            items, next_index = _consume_list(tokens, i)
            block_index = len(blocks) + 1
            ordered = token.type == "ordered_list_open"
            text_value = "\n".join(
                f"{index}. {item}" if ordered else f"• {item}"
                for index, item in enumerate(items, start=1)
            )
            block = make_block(
                block_index,
                kind="list",
                text=text_value,
                source=_source(source_file, token, "markdown", block_index, i + 1),
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i = next_index
            continue

        if token.type == "blockquote_open":
            quote_text, next_index = _consume_blockquote(tokens, i)
            block_index = len(blocks) + 1
            block = make_block(
                block_index,
                kind="paragraph",
                text=quote_text,
                source=_source(source_file, token, "markdown", block_index, i + 1),
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i = next_index
            continue

        if token.type == "math_block":
            block_index = len(blocks) + 1
            block = make_block(
                block_index,
                kind="equation",
                text=token.content.strip(),
                source=_source(source_file, token, "markdown", block_index, i + 1),
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i += 1
            continue

        if token.type == "html_block":
            add_warning(
                warnings,
                "raw_html",
                "检测到原始 HTML，已保留为待处理块；首版不渲染 HTML",
            )
            block_index = len(blocks) + 1
            block = make_block(
                block_index,
                kind="unknown",
                text=token.content.strip(),
                source=_source(source_file, token, "markdown", block_index, i + 1),
            )
            blocks.append(block)
            previous_block_id = block.id
            last_figure = None
            i += 1
            continue

        i += 1

    if pending_table is not None:
        add_warning(
            warnings,
            "missing_table_data",
            f"{pending_table.label or '表'} 有题注但没有可识别的 Markdown 表格",
        )
    if not blocks:
        add_warning(warnings, "empty_document", "没有解析到任何内容块", severity="error")

    title = title_candidate or detect_title(blocks)
    document = Document(
        title=title,
        format="markdown",
        encoding=encoding,
        source_name=source_file.name,
        source_file=workspace.source_file,
        blocks=blocks,
        figures=figures,
        tables=tables,
        warnings=warnings,
    )
    summary = ImportSummary(
        source_name=source_file.name,
        format="Markdown",
        encoding=encoding,
        block_count=len(blocks),
        heading_count=sum(1 for block in blocks if block.kind == "heading"),
        figure_count=len(figures),
        table_count=len(tables),
        warning_count=len(warnings),
    )
    return ImportResult(
        document=document,
        summary=summary,
        project_dir=str(workspace.root),
        source_copy=workspace.source_file,
    )


def _heading_level(tag: str) -> int:
    match = re.search(r"(\d+)", tag)
    return int(match.group(1)) if match else 1


def _next_inline(tokens: list[Token], index: int) -> Token | None:
    for token in tokens[index + 1 : index + 3]:
        if token.type == "inline":
            return token
    return None


def _parse_inline(
    token: Token | None,
    *,
    source_dir: Path,
    workspace: ProjectWorkspace,
) -> tuple[list[Run], list[tuple[str, str]], list[str]]:
    if token is None or not token.children:
        return [], [], []
    runs: list[Run] = []
    images: list[tuple[str, str]] = []
    warnings: list[str] = []
    bold = 0
    italic = 0
    for child in token.children:
        kind = child.type
        if kind == "text":
            runs.append(Run(text=child.content, bold=bold > 0, italic=italic > 0))
        elif kind == "strong_open":
            bold += 1
        elif kind == "strong_close":
            bold = max(0, bold - 1)
        elif kind == "em_open":
            italic += 1
        elif kind == "em_close":
            italic = max(0, italic - 1)
        elif kind == "code_inline":
            runs.append(Run(text=child.content, code=True))
        elif kind == "math_inline":
            runs.append(Run(text=f"${child.content}$", math=True))
        elif kind in {"softbreak", "hardbreak"}:
            runs.append(Run(text=" " if kind == "softbreak" else "\n"))
        elif kind == "image":
            src = child.attrGet("src") or ""
            alt = (child.content or child.attrGet("title") or "").strip()
            images.append((src, alt))
        elif kind == "html_inline":
            warnings.append("检测到行内 HTML，已忽略")
        elif kind in {"link_open", "link_close"}:
            continue
    return runs, images, warnings


def _runs_text(runs: list[Run]) -> str:
    return "".join(run.text for run in runs)


def _add_inline_warnings(
    warnings: list[ParseWarning], messages: list[str], block_id: str | None
) -> None:
    for message in messages:
        add_warning(warnings, "raw_html", message, block_id=block_id)


def _source(
    source_file: Path,
    token: Token,
    format_name: str,
    block_index: int,
    fallback_line: int,
):
    line_map = token.map or [fallback_line - 1, fallback_line]
    start = max(1, line_map[0] + 1)
    end = max(start, line_map[1])
    return source_ref(
        source_file.name,
        format_name=format_name,
        line_start=start,
        line_end=end,
        block_index=block_index,
    )


def _add_images(
    images: list[tuple[str, str]],
    *,
    blocks: list,
    figures: list[Figure],
    warnings: list[ParseWarning],
    start_block_number: int,
    source: SourceRef,
    source_dir: Path,
    workspace: ProjectWorkspace,
    start_index: int,
    anchor_after: str | None,
) -> None:
    for offset, (src, alt) in enumerate(images, start=1):
        figure_number = start_index + offset
        block_number = start_block_number + offset - 1
        figure = figure_from_caption(
            alt or f"图{figure_number}",
            figure_id=f"fig_{figure_number:03d}",
            anchor_after_block=anchor_after,
            source_dir=source_dir,
            workspace=workspace,
            image_ref=src,
            alt=alt,
        )
        if not figure.label:
            figure.label = f"图{figure_number}"
        figures.append(figure)
        block = make_block(
            block_number,
            kind="figure",
            text=figure.caption or figure.label,
            source=source.model_copy(update={"block_index": block_number}),
            asset_id=figure.id,
        )
        blocks.append(block)
        for message in figure.warnings:
            add_warning(
                warnings,
                "image_issue",
                f"{figure.label or '图'}：{message}",
                block_id=block.id,
            )


def _caption_figure(
    text: str,
    *,
    figure_index: int,
    anchor_after_block: str | None,
    last_figure: Figure | None,
    source_dir: Path,
    workspace: ProjectWorkspace,
) -> Figure:
    parts = caption_parts(text, table=False)
    if (
        last_figure is not None
        and parts is not None
        and (not last_figure.label or last_figure.label == parts[0])
    ):
        last_figure.label = parts[0]
        last_figure.caption = parts[1]
        return last_figure
    return figure_from_caption(
        text,
        figure_id=f"fig_{figure_index:03d}",
        anchor_after_block=anchor_after_block,
        source_dir=source_dir,
        workspace=workspace,
        image_ref="",
        alt="",
    )


def _consume_table(tokens: list[Token], start: int) -> tuple[list[list[str]], int, int]:
    rows: list[list[str]] = []
    row: list[str] = []
    header_rows = 0
    i = start + 1
    while i < len(tokens):
        token = tokens[i]
        if token.type == "table_close":
            return rows, header_rows or 1, i + 1
        if token.type == "thead_close":
            if row:
                rows.append(row)
                row = []
            header_rows = len(rows) or 1
        elif token.type == "tr_open":
            row = []
        elif token.type in {"th_open", "td_open"}:
            cell = _cell_text(tokens, i)
            row.append(cell)
        elif token.type == "tr_close" and row:
            rows.append(row)
            row = []
        i += 1
    return rows, header_rows or 1, i


def _cell_text(tokens: list[Token], index: int) -> str:
    for token in tokens[index + 1 : index + 2]:
        if token.type == "inline":
            if token.children:
                parts: list[str] = []
                for child in token.children:
                    if child.type in {"text", "code_inline"}:
                        parts.append(child.content)
                    elif child.type == "math_inline":
                        parts.append(f"${child.content}$")
                return "".join(parts).strip()
            return token.content.strip()
    return ""


def _consume_list(tokens: list[Token], start: int) -> tuple[list[str], int]:
    items: list[str] = []
    depth = 0
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            depth += 1
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            depth -= 1
            if depth == 0:
                return items, i + 1
        elif token.type == "inline" and token.content.strip():
            items.append(token.content.strip())
        i += 1
    return items, i


def _consume_blockquote(tokens: list[Token], start: int) -> tuple[str, int]:
    lines: list[str] = []
    depth = 0
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token.type == "blockquote_open":
            depth += 1
        elif token.type == "blockquote_close":
            depth -= 1
            if depth == 0:
                return "\n".join(lines).strip(), i + 1
        elif token.type == "inline" and token.content.strip():
            lines.append(token.content.strip())
        i += 1
    return "\n".join(lines).strip(), i
