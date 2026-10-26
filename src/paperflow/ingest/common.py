from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from charset_normalizer import from_bytes

from paperflow.core.document import Block, Figure, ParseWarning, Run, SourceRef, Table
from paperflow.core.project import ProjectWorkspace

FIGURE_RE = re.compile(r"^\s*图\s*(\d+(?:\s*[-—.]\s*\d+)?)\s*[：:.\s、]*(.*)$")
TABLE_RE = re.compile(r"^\s*表\s*(\d+(?:\s*[-—.]\s*\d+)?)\s*[：:.\s、]*(.*)$")
FIGURE_REF_RE = re.compile(r"(?:见|如|由)?\s*图\s*\d+(?:\s*[-—.]\s*\d+)?")
TABLE_REF_RE = re.compile(r"(?:见|如|由)?\s*表\s*\d+(?:\s*[-—.]\s*\d+)?")
HEADING_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+){0,3})[、.\s]\s*(\S.{0,80})$")
HEADING_CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百千]+[章节篇])\s*(.*)$")
SPECIAL_HEADINGS = {
    "引言": 1,
    "绪论": 1,
    "结论": 1,
    "结语": 1,
    "参考文献": 1,
    "致谢": 1,
}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

logger = logging.getLogger(__name__)


def make_block(
    index: int,
    *,
    kind: str,
    text: str,
    source: SourceRef,
    runs: list[Run] | None = None,
    heading_level: int | None = None,
    asset_id: str | None = None,
    warnings: list[str] | None = None,
) -> Block:
    return Block(
        id=f"B{index:04d}",
        kind=kind,
        text=text,
        heading_level=heading_level,
        runs=runs if runs is not None else [Run(text=text)] if text else [],
        source=source,
        asset_id=asset_id,
        warnings=list(warnings or []),
    )


def source_ref(
    file_name: str,
    *,
    format_name: str,
    line_start: int,
    line_end: int,
    block_index: int,
) -> SourceRef:
    return SourceRef(
        file=file_name,
        line_start=max(1, line_start),
        line_end=max(line_start, line_end),
        format=format_name,
        block_index=block_index,
    )


def classify_text_line(text: str) -> tuple[str, int | None, str]:
    """Return (kind, level, cleaned_text) for a plain-text line."""
    cleaned = text.strip()
    if not cleaned:
        return "paragraph", None, ""
    if re.match(r"^摘\s*要\s*[:：]", cleaned) or cleaned in {"摘要", "摘 要"}:
        return "abstract", None, cleaned
    if re.match(r"^关键词\s*[:：]", cleaned) or cleaned.startswith("关键字"):
        return "keywords", None, cleaned
    if FIGURE_RE.match(cleaned):
        return "figure_caption", None, cleaned
    if TABLE_RE.match(cleaned):
        return "table_caption", None, cleaned
    if cleaned in SPECIAL_HEADINGS:
        return "heading", SPECIAL_HEADINGS[cleaned], cleaned
    if cleaned.startswith("附录") and len(cleaned) <= 30:
        return "heading", 1, cleaned
    match = HEADING_CHAPTER_RE.match(cleaned)
    if match and len(cleaned) <= 80:
        return "heading", 1, cleaned
    match = HEADING_NUMBER_RE.match(cleaned)
    if match:
        level = min(4, match.group(1).count(".") + 1)
        return "heading", level, cleaned
    if len(cleaned) <= 40 and cleaned.endswith(("：", ":")) and not cleaned.endswith("。"):
        # A short label line is often a heading, but do not over-classify it.
        return "paragraph", None, cleaned
    return "paragraph", None, cleaned


def caption_parts(text: str, *, table: bool = False) -> tuple[str, str] | None:
    match = (TABLE_RE if table else FIGURE_RE).match(text.strip())
    if not match:
        return None
    number = re.sub(r"\s+", "", match.group(1))
    label = ("表" if table else "图") + number
    caption = match.group(2).strip()
    return label, caption


def detect_title(blocks: list[Block]) -> str:
    special = {"摘要", "关键词", "引言", "绪论", "参考文献", "致谢", "结论", "结语"}
    for block in blocks[:5]:
        text = block.text.strip().lstrip("#").strip()
        if not text:
            continue
        if block.kind == "heading" and block.heading_level == 1 and text not in special:
            return text[:160]
        if block.kind == "paragraph" and len(text) <= 160:
            return text.splitlines()[0][:160]
    for block in blocks:
        if block.kind == "heading" and block.text.strip():
            return block.text.strip().lstrip("#").strip()[:160]
    return "未命名论文"


def copy_markdown_image(
    raw_path: str,
    *,
    source_dir: Path,
    workspace: ProjectWorkspace,
    figure_id: str,
) -> tuple[str, str, str, list[str]]:
    """Copy a local Markdown image into the project.

    Returns (relative_path, status, source_path, warnings).
    Remote URLs are never downloaded.
    """
    value = raw_path.strip()
    if not value:
        return "", "missing", "", ["图片路径为空"]
    if re.match(r"^https?://", value, flags=re.IGNORECASE) or value.startswith("data:"):
        return "", "remote", value, ["远程图片不自动下载，请上传本地图片"]
    path = Path(value)
    if not path.is_absolute():
        path = source_dir / path
    try:
        resolved = path.resolve()
    except OSError:
        return "", "missing", value, ["图片路径无法解析"]
    source_root = source_dir.resolve()
    if not _is_relative_to(resolved, source_root):
        return "", "missing", value, ["图片路径在论文目录之外，已拒绝自动读取"]
    if not resolved.is_file():
        return "", "missing", value, ["图片文件不存在"]
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        return "", "unsupported", value, [f"不支持的图片格式：{suffix or '无扩展名'}"]
    target = workspace.figures_dir / f"{figure_id.lower()}{suffix}"
    try:
        shutil.copy2(resolved, target)
    except OSError as exc:
        return "", "missing", value, [f"图片复制失败：{exc}"]
    return workspace.relative(target), "ready", value, []


def figure_from_caption(
    text: str,
    *,
    figure_id: str,
    anchor_after_block: str | None,
    source_dir: Path,
    workspace: ProjectWorkspace | None,
    image_ref: str = "",
    alt: str = "",
) -> Figure:
    parts = caption_parts(text, table=False)
    label = parts[0] if parts else ""
    caption = parts[1] if parts else (alt or text.strip())
    figure = Figure(
        id=figure_id,
        label=label,
        caption=caption or alt,
        alt_text=alt,
        anchor_after_block=anchor_after_block,
    )
    if image_ref:
        if workspace is None:
            figure.source_path = image_ref
            figure.path = image_ref
            figure.status = "ready"
        else:
            rel, status, source_path, warnings = copy_markdown_image(
                image_ref,
                source_dir=source_dir,
                workspace=workspace,
                figure_id=figure_id,
            )
            figure.path = rel
            figure.source_path = source_path
            figure.status = status
            figure.warnings.extend(warnings)
    else:
        figure.status = "missing"
        figure.warnings.append("尚未提供图片素材")
    return figure


def table_from_caption(
    text: str,
    *,
    table_id: str,
    anchor_after_block: str | None,
    rows: list[list[str]] | None = None,
    header_rows: int = 1,
) -> Table:
    parts = caption_parts(text, table=True)
    label = parts[0] if parts else ""
    caption = parts[1] if parts else text.strip()
    return Table(
        id=table_id,
        label=label,
        caption=caption,
        rows=rows or [],
        header_rows=header_rows,
        anchor_after_block=anchor_after_block,
        status="ready" if rows else "pending",
        warnings=[] if rows else ["表格数据待补充"],
    )


def add_warning(
    warnings: list[ParseWarning],
    code: str,
    message: str,
    *,
    block_id: str | None = None,
    severity: str = "warning",
) -> None:
    warnings.append(
        ParseWarning(
            code=code,
            message=message,
            block_id=block_id,
            severity=severity,  # type: ignore[arg-type]
        )
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8"
    best = from_bytes(data).best()
    if best is not None:
        try:
            return str(best), _display_encoding(best.encoding or "utf-8")
        except Exception:
            logger.debug("Encoding detection conversion failed", exc_info=True)
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8 (replacement)"


def _display_encoding(encoding: str) -> str:
    normalized = encoding.lower().replace("_", "-")
    if normalized.startswith("utf-8"):
        return "utf-8"
    if normalized in {"gb2312", "gbk", "gb18030"}:
        return "gb18030"
    return encoding