from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperflow.core.document import Block, Document

ROLE_VALUES = (
    "title",
    "subtitle",
    "author",
    "affiliation",
    "abstract",
    "keywords",
    "heading",
    "paragraph",
    "list",
    "code",
    "figure",
    "figure_caption",
    "table",
    "table_caption",
    "equation",
    "reference",
    "acknowledgement",
    "appendix",
    "unknown",
)


class StructureBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block_id: str
    role: str = "paragraph"
    heading_level: int | None = None
    confidence: float = 0.5
    note: str = ""

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        value = value.strip()
        if value not in ROLE_VALUES:
            raise ValueError(f"未知角色：{value}")
        return value

    @field_validator("heading_level")
    @classmethod
    def validate_level(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return min(4, max(1, int(value)))

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        return min(1.0, max(0.0, float(value)))

    @model_validator(mode="after")
    def normalize_heading(self) -> StructureBlock:
        if self.role == "heading" and self.heading_level is None:
            self.heading_level = 1
        if self.role != "heading":
            self.heading_level = None
        return self


class StructureMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    language: str = "zh"


class StructureResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metadata: StructureMetadata = Field(default_factory=StructureMetadata)
    blocks: list[StructureBlock] = Field(default_factory=list)


class SectionNode(BaseModel):
    id: str
    title: str
    level: int = 1
    block_id: str | None = None
    block_ids: list[str] = Field(default_factory=list)
    children: list[SectionNode] = Field(default_factory=list)


SectionNode.model_rebuild()


class StructureResult(BaseModel):
    document: Document
    metadata: StructureMetadata = Field(default_factory=StructureMetadata)
    blocks: list[StructureBlock] = Field(default_factory=list)
    sections: list[SectionNode] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    source: Literal["ai", "local", "manual"] = "local"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    request_id: str = ""

    @property
    def usage_text(self) -> str:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return ""
        return f"输入 {self.prompt_tokens or 0} / 输出 {self.completion_tokens or 0} tokens"

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class StructureValidationError(ValueError):
    def __init__(self, message: str, *, missing: list[str] | None = None, extra: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []
        self.extra = extra or []


def build_local_structure(document: Document) -> StructureResult:
    metadata = _metadata_from_blocks(document)
    items: list[StructureBlock] = []
    for index, block in enumerate(document.blocks):
        role = block.kind if block.kind in ROLE_VALUES else "unknown"
        level = block.heading_level
        text_value = block.text.strip()
        if index == 0 and text_value == document.title.strip():
            role = "title"
            level = None
        elif metadata.authors and _split_authors(text_value) == metadata.authors:
            role = "author"
            level = None
        elif metadata.affiliations and text_value in metadata.affiliations:
            role = "affiliation"
            level = None
        if role == "heading" and level is None:
            level = 1
        if role != "heading":
            level = None
        items.append(
            StructureBlock(
                block_id=block.id,
                role=role,
                heading_level=level,
                confidence=0.78 if role not in {"unknown"} else 0.35,
                note="" if role != "unknown" else "本地规则未能判断类型",
            )
        )

    updated = _apply_items(document, items)
    issues = _local_issues(updated)
    return StructureResult(
        document=updated,
        metadata=metadata,
        blocks=items,
        sections=build_sections(updated),
        issues=issues,
        source="local",
    )


def apply_structure_response(
    document: Document,
    response: StructureResponse,
    *,
    source: Literal["ai", "manual"] = "ai",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    request_id: str = "",
) -> StructureResult:
    validate_coverage(document, response)
    items = response.blocks
    updated = _apply_items(document, items)
    metadata = response.metadata
    if not metadata.title.strip():
        metadata = metadata.model_copy(update={"title": document.title})
    issues = [
        f"{item.block_id}：{item.note}"
        for item in items
        if item.note.strip() and item.confidence < 0.8
    ]
    issues.extend(_local_issues(updated))
    return StructureResult(
        document=updated,
        metadata=metadata,
        blocks=items,
        sections=build_sections(updated),
        issues=issues,
        source=source,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        request_id=request_id,
    )


def validate_coverage(document: Document, response: StructureResponse) -> None:
    expected = [block.id for block in document.blocks]
    actual = [item.block_id for item in response.blocks]
    if len(actual) != len(set(actual)):
        duplicates = sorted({block_id for block_id in actual if actual.count(block_id) > 1})
        raise StructureValidationError(
            f"模型返回了重复块：{', '.join(duplicates[:8])}",
            extra=duplicates,
        )
    missing = [block_id for block_id in expected if block_id not in set(actual)]
    extra = [block_id for block_id in actual if block_id not in set(expected)]
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"缺少 {len(missing)} 块：{', '.join(missing[:8])}")
        if extra:
            parts.append(f"多出 {len(extra)} 块：{', '.join(extra[:8])}")
        raise StructureValidationError("；".join(parts), missing=missing, extra=extra)


def build_sections(document: Document) -> list[SectionNode]:
    roots: list[SectionNode] = []
    stack: list[SectionNode] = []
    front = SectionNode(id="S000", title="文前内容", level=0)
    roots.append(front)
    current = front
    section_index = 0
    for block in document.blocks:
        if block.kind == "heading" and block.text.strip():
            section_index += 1
            level = block.heading_level or 1
            node = SectionNode(
                id=f"S{section_index:03d}",
                title=block.text.strip(),
                level=level,
                block_id=block.id,
            )
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
            current = node
        else:
            current.block_ids.append(block.id)
    return roots


def _apply_items(document: Document, items: list[StructureBlock]) -> Document:
    by_id = {item.block_id: item for item in items}
    blocks: list[Block] = []
    for block in document.blocks:
        item = by_id.get(block.id)
        if item is None:
            blocks.append(block)
            continue
        blocks.append(
            block.model_copy(
                update={
                    "kind": item.role,
                    "heading_level": item.heading_level,
                }
            )
        )
    return document.model_copy(update={"blocks": blocks})


def _metadata_from_blocks(document: Document) -> StructureMetadata:
    authors: list[str] = []
    affiliations: list[str] = []
    abstract = ""
    keywords: list[str] = []
    for block in document.blocks:
        text = block.text.strip()
        if block.kind == "abstract" and not abstract:
            abstract = re.sub(r"^摘\s*要\s*[:：]\s*", "", text).strip()
        elif block.kind == "keywords" and not keywords:
            value = re.sub(r"^(关\s*键\s*词|关键字)\s*[:：]\s*", "", text)
            keywords = _split_keywords(value)
        elif not authors and _looks_like_authors(text):
            authors = _split_authors(text)
        elif authors and not affiliations and _looks_like_affiliation(text):
            affiliations = [text]
        if block.kind in {"abstract", "keywords"}:
            continue
    return StructureMetadata(
        title=document.title,
        authors=authors,
        affiliations=affiliations,
        abstract=abstract,
        keywords=keywords,
    )


def _looks_like_authors(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    if any(marker in text for marker in ("大学", "学院", "摘要", "关键词", "图", "表")):
        return False
    return bool(re.search(r"[，,、；;]", text))


def _looks_like_affiliation(text: str) -> bool:
    return any(marker in text for marker in ("大学", "学院", "研究所", "实验室", "公司"))


def _split_authors(text: str) -> list[str]:
    parts = re.split(r"[，,、；;]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def _split_keywords(text: str) -> list[str]:
    parts = re.split(r"[；;，,、]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def _local_issues(document: Document) -> list[str]:
    issues: list[str] = []
    for block in document.blocks:
        if block.kind == "unknown":
            issues.append(f"{block.id}：类型未确定")
        elif block.kind == "heading" and not block.heading_level:
            issues.append(f"{block.id}：标题缺少级别")
    return issues