from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Run(BaseModel):
    text: str = ""
    bold: bool = False
    italic: bool = False
    code: bool = False
    math: bool = False


class SourceRef(BaseModel):
    file: str = ""
    line_start: int = 1
    line_end: int = 1
    format: Literal["txt", "markdown"] = "txt"
    block_index: int = 0


class Block(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str = "paragraph"
    text: str = ""
    heading_level: int | None = None
    runs: list[Run] = Field(default_factory=list)
    source: SourceRef = Field(default_factory=SourceRef)
    asset_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class Figure(BaseModel):
    id: str
    label: str = ""
    caption: str = ""
    caption_en: str = ""
    alt_text: str = ""
    note: str = ""
    path: str = ""
    source_path: str = ""
    status: str = "pending"  # ready / pending / missing / remote / unsupported
    anchor_after_block: str | None = None
    width_ratio: float = 0.8
    span_columns: bool = False
    placement: str = "htbp"
    warnings: list[str] = Field(default_factory=list)


class Table(BaseModel):
    id: str
    label: str = ""
    caption: str = ""
    caption_en: str = ""
    note: str = ""
    rows: list[list[str]] = Field(default_factory=list)
    header_rows: int = 1
    anchor_after_block: str | None = None
    span_columns: bool = False
    style: str = "three_line"
    status: str = "ready"  # ready / pending / unsupported
    warnings: list[str] = Field(default_factory=list)


class ParseWarning(BaseModel):
    code: str
    message: str
    block_id: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


class ImportSummary(BaseModel):
    source_name: str = ""
    format: str = ""
    encoding: str = ""
    block_count: int = 0
    heading_count: int = 0
    figure_count: int = 0
    table_count: int = 0
    warning_count: int = 0


class Document(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    title: str = ""
    format: Literal["txt", "markdown"] = "txt"
    encoding: str = "utf-8"
    source_name: str = ""
    source_file: str = ""
    blocks: list[Block] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    warnings: list[ParseWarning] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class ImportResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    document: Document
    summary: ImportSummary
    project_dir: str = ""
    source_copy: str = ""