from __future__ import annotations

from pathlib import Path

from paperflow.core.metadata import build_m4_state
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document
from paperflow.ui.assets_page import AssetsPage


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    return imported, structure, build_m4_state(imported, structure)


def test_assets_page_loads_figures_and_tables(qtbot, tmp_path: Path) -> None:
    imported, structure, state = _context(tmp_path)
    page = AssetsPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    assert page.asset_list.count() == 2
    assert page.editor_stack.currentIndex() == 1
    page.asset_list.setCurrentRow(1)
    assert page.editor_stack.currentIndex() == 2
    assert page.table_editor.rowCount() == 3
    assert page.table_editor.columnCount() == 5

    page.save_assets()
    assert (Path(imported.project_dir) / "content" / "assets.json").is_file()
    assert page.next_button.isEnabled() is True


def test_assets_page_table_edit_and_paste(qtbot, tmp_path: Path) -> None:
    imported, structure, state = _context(tmp_path)
    page = AssetsPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)
    page.asset_list.setCurrentRow(1)

    page.add_table_row()
    page.add_table_column()
    assert page.table_editor.rowCount() == 4
    assert page.table_editor.columnCount() == 6

    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText("A\tB\n1\t2")
    page.paste_table()
    assert page.table_editor.rowCount() == 2
    assert page.table_editor.columnCount() == 2
    assert page.table_editor.item(0, 0).text() == "A"


def test_assets_page_upload_figure(qtbot, tmp_path: Path, monkeypatch) -> None:
    imported, structure, state = _context(tmp_path)
    page = AssetsPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    page.asset_list.setCurrentRow(0)
    monkeypatch.setattr(
        "paperflow.ui.assets_page.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(Path("examples/assets/fig1.png").resolve()), ""),
    )
    page.upload_figure()
    figure = state.figures[0]
    assert figure.status == "ready"
    assert (Path(imported.project_dir) / figure.path).is_file()
    assert page.figure_status.text() == "状态：已关联"