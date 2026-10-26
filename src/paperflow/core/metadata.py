from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from paperflow.core.document import Document, Figure, ImportResult, Table
from paperflow.core.structure import StructureResult

FieldSource = Literal["body", "ai", "manual", "default"]


class FieldValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str = ""
    source: FieldSource = "default"
    evidence_block_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.value.strip()


class AuthorEntry(BaseModel):
    name: str = ""
    name_en: str = ""
    affiliation_indices: list[int] = Field(default_factory=list)
    corresponding: bool = False
    email: str = ""
    source: FieldSource = "manual"


class AffiliationEntry(BaseModel):
    name: str = ""
    name_en: str = ""
    department: str = ""
    city: str = ""
    postcode: str = ""
    country: str = "中国"
    source: FieldSource = "manual"


class FundEntry(BaseModel):
    name: str = ""
    number: str = ""
    title: str = ""
    source: FieldSource = "manual"


class AuthorBio(BaseModel):
    author_name: str = ""
    text: str = ""
    source: FieldSource = "manual"


class MetadataConflict(BaseModel):
    field: str
    label: str
    body_value: str
    form_value: str
    resolved: bool = False
    kind: str = "different"  # different / fund_off


class MetadataState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: FieldValue = Field(default_factory=FieldValue)
    title_en: FieldValue = Field(default_factory=FieldValue)
    subtitle: FieldValue = Field(default_factory=FieldValue)
    abstract: FieldValue = Field(default_factory=FieldValue)
    abstract_en: FieldValue = Field(default_factory=FieldValue)
    clc_number: FieldValue = Field(default_factory=FieldValue)
    document_type: FieldValue = Field(default_factory=FieldValue)
    article_number: FieldValue = Field(default_factory=FieldValue)
    doi: FieldValue = Field(default_factory=FieldValue)
    received_date: FieldValue = Field(default_factory=FieldValue)
    acknowledgement: FieldValue = Field(default_factory=FieldValue)
    notes: FieldValue = Field(default_factory=FieldValue)

    authors: list[AuthorEntry] = Field(default_factory=list)
    affiliations: list[AffiliationEntry] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    author_bios: list[AuthorBio] = Field(default_factory=list)
    funds: list[FundEntry] = Field(default_factory=list)
    fund_enabled: bool = False
    fund_off_confirmed: bool = False

    authors_source: FieldSource = "default"
    affiliations_source: FieldSource = "default"
    keywords_source: FieldSource = "default"
    funds_source: FieldSource = "default"
    bios_source: FieldSource = "default"

    body_title: str = ""
    body_authors: list[str] = Field(default_factory=list)
    body_affiliations: list[str] = Field(default_factory=list)
    body_abstract: str = ""
    body_keywords: list[str] = Field(default_factory=list)
    body_funds: list[str] = Field(default_factory=list)
    body_bios: list[str] = Field(default_factory=list)

    consumed_block_ids: list[str] = Field(default_factory=list)
    conflicts: list[MetadataConflict] = Field(default_factory=list)

    @property
    def unresolved_conflicts(self) -> list[MetadataConflict]:
        return [conflict for conflict in self.conflicts if not conflict.resolved]

    def mark_form_priority(self) -> None:
        for conflict in self.conflicts:
            conflict.resolved = True

    def detect_conflicts(self) -> list[MetadataConflict]:
        previous = {
            (conflict.field, conflict.body_value, conflict.form_value): conflict.resolved
            for conflict in self.conflicts
        }
        conflicts: list[MetadataConflict] = []
        _compare_field(conflicts, "title", "题名", self.body_title, self.title.value)
        _compare_field(
            conflicts,
            "authors",
            "作者",
            _join(self.body_authors),
            _join([author.name for author in self.authors]),
        )
        _compare_field(
            conflicts,
            "affiliations",
            "单位",
            _join(self.body_affiliations),
            _join([affiliation.name for affiliation in self.affiliations]),
        )
        _compare_field(conflicts, "abstract", "摘要", self.body_abstract, self.abstract.value)
        _compare_field(
            conflicts,
            "keywords",
            "关键词",
            "；".join(self.body_keywords),
            "；".join(self.keywords),
        )
        if self.body_funds and not self.fund_enabled and not self.fund_off_confirmed:
            conflicts.append(
                MetadataConflict(
                    field="fund_off",
                    label="基金开关",
                    body_value="正文含基金信息",
                    form_value="基金开关关闭",
                    kind="fund_off",
                )
            )
        for conflict in conflicts:
            conflict.resolved = previous.get(
                (conflict.field, conflict.body_value, conflict.form_value), False
            )
        self.conflicts = conflicts
        return conflicts

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class M4State(BaseModel):
    metadata: MetadataState = Field(default_factory=MetadataState)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    saved_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


def build_m4_state(imported: ImportResult, structure: StructureResult) -> M4State:
    document = structure.document
    metadata = _metadata_from_structure(document, structure)
    figures = [figure.model_copy(deep=True) for figure in imported.document.figures]
    tables = [table.model_copy(deep=True) for table in imported.document.tables]
    return M4State(metadata=metadata, figures=figures, tables=tables)


def _metadata_from_structure(document: Document, structure: StructureResult) -> MetadataState:
    roles = {item.block_id: item.role for item in structure.blocks}
    evidence = _evidence_map(document, roles)
    source: FieldSource = "ai" if structure.source == "ai" else "body"
    meta = structure.metadata

    title = FieldValue(
        value=meta.title or document.title,
        source=source,
        evidence_block_ids=evidence.get("title", []),
        confirmed=False,
    )
    abstract = FieldValue(
        value=meta.abstract,
        source=source,
        evidence_block_ids=evidence.get("abstract", []),
    )
    authors = [
        AuthorEntry(
            name=name.strip(),
            source=source,
        )
        for name in meta.authors
        if name.strip()
    ]
    affiliations = [
        AffiliationEntry(name=name.strip(), source=source)
        for name in meta.affiliations
        if name.strip()
    ]
    keywords = [item.strip() for item in meta.keywords if item.strip()]
    if len(affiliations) == 1:
        for author in authors:
            author.affiliation_indices = [1]
    body_funds, body_bios, fund_blocks, bio_blocks = _fund_and_bio_candidates(
        document, roles
    )
    funds = [
        FundEntry(name=text[:120], source="body")
        for text in body_funds
    ]
    bios = [
        AuthorBio(author_name="", text=text, source="body")
        for text in body_bios
    ]
    consumed = sorted(
        set(
            evidence.get("title", [])
            + evidence.get("author", [])
            + evidence.get("affiliation", [])
            + evidence.get("abstract", [])
            + evidence.get("keywords", [])
            + fund_blocks
            + (bio_blocks if bios else [])
        )
    )
    metadata = MetadataState(
        title=title,
        abstract=abstract,
        authors=authors,
        affiliations=affiliations,
        keywords=keywords,
        author_bios=bios,
        funds=funds,
        fund_enabled=bool(funds),
        authors_source=source if authors else "default",
        affiliations_source=source if affiliations else "default",
        keywords_source=source if keywords else "default",
        funds_source="body" if funds else "default",
        bios_source="body" if bios else "default",
        body_title=meta.title or document.title,
        body_authors=list(meta.authors),
        body_affiliations=list(meta.affiliations),
        body_abstract=meta.abstract,
        body_keywords=list(meta.keywords),
        body_funds=body_funds,
        body_bios=body_bios,
        consumed_block_ids=consumed,
    )
    metadata.detect_conflicts()
    return metadata


def _evidence_map(document: Document, roles: dict[str, str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for block in document.blocks:
        role = roles.get(block.id, block.kind)
        if role in {"title", "author", "affiliation", "abstract", "keywords"}:
            mapping.setdefault(role, []).append(block.id)
    return mapping


def _fund_and_bio_candidates(
    document: Document, roles: dict[str, str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    funds: list[str] = []
    bios: list[str] = []
    fund_blocks: list[str] = []
    bio_blocks: list[str] = []
    for block in document.blocks:
        text = block.text.strip()
        role = roles.get(block.id, block.kind)
        if not text:
            continue
        if "基金" in text and ("项目" in text or "资助" in text):
            if role == "heading":
                continue
            funds.append(re.sub(r"^\s*基金(项目)?\s*[:：]\s*", "", text))
            fund_blocks.append(block.id)
        elif text.startswith(("作者简介", "作者介绍")) or (
            "作者简介" in text and len(text) <= 600
        ):
            bios.append(re.sub(r"^\s*作者简介\s*[:：]\s*", "", text))
            bio_blocks.append(block.id)
    return funds, bios, fund_blocks, bio_blocks


def _compare_field(
    conflicts: list[MetadataConflict],
    field: str,
    label: str,
    body_value: str,
    form_value: str,
) -> None:
    body_clean = (body_value or "").strip()
    form_clean = (form_value or "").strip()
    if body_clean and form_clean and body_clean != form_clean:
        conflicts.append(
            MetadataConflict(
                field=field,
                label=label,
                body_value=body_clean,
                form_value=form_clean,
            )
        )


def _join(values: list[str]) -> str:
    return "、".join(value for value in values if value.strip())