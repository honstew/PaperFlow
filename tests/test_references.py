from __future__ import annotations

from pathlib import Path

from paperflow.core.references import generate_bib, parse_reference_text, parse_references
from paperflow.core.structure import StructureResult, build_local_structure
from paperflow.ingest import import_document


def _structure(tmp_path: Path) -> StructureResult:
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    return build_local_structure(imported.document)


def test_parse_demo_references(tmp_path: Path) -> None:
    structure = _structure(tmp_path)
    state = parse_references(structure.document, structure)

    assert len(state.entries) == 2
    first = state.entries[0]
    assert first.title == "面向学术论文的结构化排版方法"
    assert first.journal == "计算机应用"
    assert first.year == "2026"
    assert first.volume == "46"
    assert first.number == "3"
    assert first.pages == "1-9"
    bib = generate_bib(state.entries)
    assert "@article" in bib
    assert "volume = {46}" in bib
    assert "pages = {1-9}" in bib


def test_parse_reference_without_type_marker() -> None:
    entry = parse_reference_text("张三. 测试题名. 测试期刊, 2024, 12(2): 3-8.", index=1)
    assert entry.title.startswith("测试题名")
    assert entry.year == "2024"
    assert entry.authors == ["张三"]