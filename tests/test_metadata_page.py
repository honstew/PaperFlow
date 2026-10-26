from __future__ import annotations

from pathlib import Path

from paperflow.core.metadata import build_m4_state
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document
from paperflow.ui.metadata_page import MetadataPage


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    return imported, structure, build_m4_state(imported, structure)


def test_metadata_page_prefills_authors_and_saves(qtbot, tmp_path: Path) -> None:
    imported, structure, state = _context(tmp_path)
    page = MetadataPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    assert page.title_edit.text() == "面向高校论文的自动排版流程设计与实现"
    assert page.author_table.rowCount() == 2
    assert page.affiliation_table.rowCount() == 1
    assert page.authors_chip.text().endswith("正文预填")

    page.save_metadata()
    content = Path(imported.project_dir) / "content"
    assert (content / "metadata.json").is_file()
    assert (content / "m4-state.json").is_file()
    assert "B0001" in state.metadata.consumed_block_ids


def test_metadata_page_conflict_and_reload(qtbot, tmp_path: Path) -> None:
    imported, structure, state = _context(tmp_path)
    page = MetadataPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    page.title_edit.setText("用户修改后的题名")
    page.save_metadata()
    assert page.conflict_banner.isHidden() is False
    assert page.conflict_banner.title.text().startswith("发现")

    page.reload_from_body()
    assert page.title_edit.text() == "面向高校论文的自动排版流程设计与实现"


def test_metadata_page_keep_form_clears_conflict(qtbot, tmp_path: Path) -> None:
    imported, structure, state = _context(tmp_path)
    page = MetadataPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    page.title_edit.setText("用户修改后的题名")
    page.save_metadata()
    assert page.conflict_banner.isHidden() is False
    page.keep_form_values()
    page.save_metadata()
    assert page.conflict_banner.isHidden() is True


def test_metadata_page_fund_off_warning(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    paper = source / "fund.md"
    paper.write_text(
        "# 有基金的论文\n\n张三\n\n某某大学\n\n摘要：测试。\n\n关键词：测试\n\n"
        "基金项目：国家自然科学基金（62000000）\n\n## 1 引言\n\n正文。\n",
        encoding="utf-8",
    )
    imported = import_document(paper, projects_dir=tmp_path / "projects")
    structure = build_local_structure(imported.document)
    state = build_m4_state(imported, structure)
    page = MetadataPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, state)

    page.fund_check.setChecked(False)
    assert "关闭需确认" in page.fund_note.text()