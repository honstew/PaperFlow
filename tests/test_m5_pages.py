from __future__ import annotations

from pathlib import Path

from paperflow.core.compile import CompileResult
from paperflow.core.config import AppSettings
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import build_m4_state
from paperflow.core.references import parse_references
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document
from paperflow.ui.build_page import BuildPage
from paperflow.ui.layout_page import LayoutPage
from paperflow.ui.references_page import ReferencesPage


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    m4 = build_m4_state(imported, structure)
    references = parse_references(structure.document, structure)
    return imported, structure, m4, references


def test_references_page_saves_bib(qtbot, tmp_path: Path) -> None:
    imported, structure, _, references = _context(tmp_path)
    page = ReferencesPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, references)

    assert page.table.rowCount() == 2
    page.confirm_all()
    page.save_references()

    assert (Path(imported.project_dir) / "content" / "references.json").is_file()
    assert (Path(imported.project_dir) / "output" / "refs.bib").is_file()
    assert page.next_button.isEnabled()


def test_layout_page_saves_json(qtbot, tmp_path: Path) -> None:
    imported, _, _, _ = _context(tmp_path)
    page = LayoutPage()
    qtbot.addWidget(page)
    page.set_context(Path(imported.project_dir), LayoutSettings())
    page.columns_combo.setCurrentIndex(page.columns_combo.findData(2))
    page.save_layout()

    assert (Path(imported.project_dir) / "content" / "layout.json").is_file()
    assert page.next_button.isEnabled()


def test_build_page_renders_tex(qtbot, tmp_path: Path) -> None:
    imported, structure, m4, references = _context(tmp_path)
    page = BuildPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, m4, references, LayoutSettings())

    assert page.generate_tex() is True
    assert (Path(imported.project_dir) / "output" / "main.tex").is_file()
    assert page.open_tex_button.isEnabled() is True
    page.set_ai_context(AppSettings(), lambda: "sk-test")
    page._compile_result = CompileResult(False, None, "error", 0.0)
    page.refresh_compile_fix_state()
    assert page.ai_fix_button.isEnabled() is True