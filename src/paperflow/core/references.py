from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from paperflow.core.document import Document
from paperflow.core.structure import StructureResult

REFERENCE_MARK = re.compile(r"^\s*\[?\s*(\d+)\s*\]?\s*[.、]?\s*")
TYPE_MARK = re.compile(r"\[(J|M|C|D|P|R|S|N|EB/OL|DB/OL|J/OL|M/OL)\]", re.IGNORECASE)
YEAR_RE = re.compile(r"(19|20)\d{2}")


class ReferenceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    original_text: str
    type: str = "article"
    authors: list[str] = Field(default_factory=list)
    title: str = ""
    journal: str = ""
    booktitle: str = ""
    publisher: str = ""
    address: str = ""
    year: str = ""
    volume: str = ""
    number: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    language: str = "chinese"
    citation_key: str = ""
    confidence: float = 0.55
    status: str = "pending"  # pending / confirmed / fallback_text / excluded
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferenceState(BaseModel):
    entries: list[ReferenceEntry] = Field(default_factory=list)
    source: str = "local"
    saved_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @property
    def confirmed_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "confirmed")


def parse_references(document: Document, structure: StructureResult) -> ReferenceState:
    roles = {item.block_id: item.role for item in structure.blocks}
    candidates = [
        block
        for block in document.blocks
        if roles.get(block.id, block.kind) == "reference" and block.text.strip()
    ]
    if not candidates:
        in_references = False
        for block in document.blocks:
            text = block.text.strip()
            if block.kind == "heading" and "参考文献" in text:
                in_references = True
                continue
            if in_references and block.kind == "heading":
                break
            if in_references and block.kind in {"paragraph", "list", "unknown"} and text:
                candidates.append(block)
    entries = [
        parse_reference_text(block.text.strip(), index=index)
        for index, block in enumerate(candidates, start=1)
    ]
    return ReferenceState(entries=entries, source="local")


def parse_reference_text(text: str, *, index: int) -> ReferenceEntry:
    original = text.strip()
    clean = REFERENCE_MARK.sub("", original)
    type_match = TYPE_MARK.search(clean)
    marker = (type_match.group(1).upper() if type_match else "").replace("/OL", "")
    ref_type = {
        "J": "article",
        "M": "book",
        "C": "inproceedings",
        "D": "phdthesis",
        "P": "patent",
        "R": "report",
        "S": "standard",
        "N": "newspaper",
        "EB": "misc",
        "DB": "misc",
    }.get(marker, "misc")

    authors: list[str] = []
    title = ""
    rest = ""
    if type_match:
        before = clean[: type_match.start()].strip()
        rest = clean[type_match.end() :].strip().lstrip(". ")
        pieces = before.split(". ", 1)
        if len(pieces) == 2:
            authors = _split_authors(pieces[0])
            title = pieces[1].strip()
        else:
            title = before
    else:
        pieces = clean.split(". ", 1)
        if len(pieces) == 2:
            authors = _split_authors(pieces[0])
            title = pieces[1].strip()
        else:
            title = clean

    year_match = YEAR_RE.search(rest or clean)
    year = year_match.group(0) if year_match else ""
    journal = ""
    volume = ""
    number = ""
    pages = ""
    publisher = ""
    address = ""
    if ref_type == "article":
        journal = _before_year(rest)
        after_year = ""
        year_match = YEAR_RE.search(rest)
        if year_match:
            after_year = rest[year_match.end() :]
        volume, number, pages = _parse_volume_pages(after_year)
    elif ref_type == "book":
        publisher, address = _parse_publisher(rest)

    citation_key = _citation_key(authors, year, index)
    missing = []
    if not authors:
        missing.append("authors")
    if not title:
        missing.append("title")
    if not year:
        missing.append("year")
    if ref_type == "article" and not journal:
        missing.append("journal")
    if ref_type == "book" and not publisher:
        missing.append("publisher")
    language = "chinese" if re.search(r"[\u4e00-\u9fff]", clean) else "english"
    return ReferenceEntry(
        id=f"ref{index:03d}",
        original_text=original,
        type=ref_type,
        authors=authors,
        title=title,
        journal=journal,
        booktitle="",
        publisher=publisher,
        address=address,
        year=year,
        volume=volume,
        number=number,
        pages=pages,
        language=language,
        citation_key=citation_key,
        confidence=0.62 if authors and title else 0.35,
        missing_fields=missing,
    )


def _split_authors(text: str) -> list[str]:
    text = text.strip().rstrip(".")
    parts = re.split(r"[，,、；;]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def _before_year(text: str) -> str:
    match = YEAR_RE.search(text)
    before = text[: match.start()].strip(" ,，.。") if match else text
    before = re.sub(r"^[Jj]\.\s*", "", before)
    return before.strip(" ,，.。")


def _parse_volume_pages(text: str) -> tuple[str, str, str]:
    volume = ""
    number = ""
    pages = ""
    match = re.search(
        r"(?:,\s*|\s)(\d+)\s*(?:\((\d+)\))?\s*(?::\s*([0-9A-Za-z\-–—]+))?",
        text,
    )
    if match:
        volume = match.group(1) or ""
        number = match.group(2) or ""
        pages = match.group(3) or ""
    return volume, number, pages


def _parse_publisher(text: str) -> tuple[str, str]:
    text = text.strip(" .。")
    if ":" in text:
        address, publisher = text.split(":", 1)
        return publisher.strip(" .。"), address.strip(" .。")
    return text.strip(" .。"), ""


def _citation_key(authors: list[str], year: str, index: int) -> str:
    if authors:
        first = authors[0]
        latin = re.sub(r"[^A-Za-z]", "", first)
        if latin:
            return f"{latin[:12]}{year or index}"
        digits = re.sub(r"\D", "", first)
        if digits:
            return f"ref{digits}{year}"
    return f"ref{index:03d}{year}"


def to_bibtex(entry: ReferenceEntry) -> str:
    kind = {
        "article": "article",
        "book": "book",
        "inproceedings": "inproceedings",
        "phdthesis": "phdthesis",
        "misc": "misc",
    }.get(entry.type, "misc")
    key = entry.citation_key or entry.id
    fields: list[tuple[str, str]] = []
    if entry.authors:
        fields.append(("author", " and ".join(entry.authors)))
    if entry.title:
        fields.append(("title", entry.title))
    if entry.journal:
        fields.append(("journal", entry.journal))
    if entry.booktitle:
        fields.append(("booktitle", entry.booktitle))
    if entry.publisher:
        fields.append(("publisher", entry.publisher))
    if entry.address:
        fields.append(("address", entry.address))
    if entry.year:
        fields.append(("year", entry.year))
    if entry.volume:
        fields.append(("volume", entry.volume))
    if entry.number:
        fields.append(("number", entry.number))
    if entry.pages:
        fields.append(("pages", entry.pages))
    if entry.doi:
        fields.append(("doi", entry.doi))
    if entry.url:
        fields.append(("url", entry.url))
    body = ",\n".join(
        f"  {name} = {{{_bib_value(value)}}}" for name, value in fields
    )
    return f"@{kind}{{{key},\n{body}\n}}\n"


def generate_bib(entries: list[ReferenceEntry]) -> str:
    chunks = [to_bibtex(entry) for entry in entries if entry.status != "excluded"]
    return "\n".join(chunks)


def _bib_value(value: str) -> str:
    return str(value).replace("{", "").replace("}", "").replace("\n", " ").strip()