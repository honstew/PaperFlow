from __future__ import annotations

import shutil
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from paperflow.core.compile import compile_tex
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import build_m4_state
from paperflow.core.references import parse_references
from paperflow.core.render import render_project
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    m4 = build_m4_state(imported, structure)
    references = parse_references(structure.document, structure)
    return imported, structure, m4, references


def test_render_project_contains_expected_latex(tmp_path: Path) -> None:
    imported, structure, m4, references = _context(tmp_path)
    result = render_project(
        Path(imported.project_dir),
        imported,
        structure,
        m4,
        references,
        LayoutSettings(),
    )

    assert result.tex_path.is_file()
    assert result.bib_path.is_file()
    tex = result.tex_path.read_text(encoding="utf-8")
    assert r"\section*{引言}" in tex
    assert r"\section{方法}" in tex
    assert r"\begin{figure}" in tex
    assert r"\begin{table}" in tex
    assert r"\addbibresource{refs.bib}" in tex
    assert "1 1 引言" not in tex
    assert "张三" in tex
    assert "面向学术论文的结构化排版方法" in result.bib_path.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="XeLaTeX not installed")
def test_compile_demo_pdf(tmp_path: Path) -> None:
    imported, structure, m4, references = _context(tmp_path)
    result = render_project(
        Path(imported.project_dir),
        imported,
        structure,
        m4,
        references,
        LayoutSettings(),
    )
    compiled = compile_tex(Path(imported.project_dir), result.tex_path, timeout_s=120)

    assert compiled.ok, compiled.log_tail
    assert compiled.pdf_path is not None
    assert compiled.pdf_path.is_file()
    document = pdfium.PdfDocument(str(compiled.pdf_path))
    try:
        assert len(document) >= 2
    finally:
        document.close()


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="XeLaTeX not installed")
def test_compile_with_non_ascii_project_path(tmp_path: Path) -> None:
    source_dir = tmp_path / "论文源文件"
    source_dir.mkdir()
    source = source_dir / "新建_文本文档_2.md"
    source.write_bytes(Path("examples/demo-paper.md").read_bytes())
    imported = import_document(source, projects_dir=tmp_path / "论文项目")
    structure = build_local_structure(imported.document)
    m4 = build_m4_state(imported, structure)
    references = parse_references(structure.document, structure)
    result = render_project(
        Path(imported.project_dir),
        imported,
        structure,
        m4,
        references,
        LayoutSettings(),
    )
    compiled = compile_tex(Path(imported.project_dir), result.tex_path, timeout_s=120)
    assert compiled.ok, compiled.log_tail