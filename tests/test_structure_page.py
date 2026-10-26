from __future__ import annotations

from pathlib import Path

from paperflow.core.config import AppSettings
from paperflow.ingest import import_document
from paperflow.ui.structure_page import StructurePage


def test_structure_page_local_baseline_and_save(qtbot, tmp_path: Path) -> None:
    result = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    page = StructurePage(lambda: AppSettings(), lambda: "")
    qtbot.addWidget(page)
    page.show()
    page.set_import_result(result)
    qtbot.wait(20)

    assert page.block_table.rowCount() == 29
    assert page.section_tree.topLevelItemCount() == 1
    assert page.section_tree.topLevelItem(0).childCount() == 6
    assert page.ai_chip.text() == "本地规则"
    assert page.working_result is not None

    page.save_structure()
    structure_file = Path(result.project_dir) / "content" / "structure.json"
    assert structure_file.is_file()
    assert structure_file.read_text(encoding="utf-8").startswith("{")


def test_structure_page_requires_key_for_ai(qtbot, tmp_path: Path) -> None:
    result = import_document(
        Path("examples/demo-paper.txt"),
        projects_dir=tmp_path / "projects",
    )
    page = StructurePage(lambda: AppSettings(), lambda: "")
    qtbot.addWidget(page)
    page.set_import_result(result)

    page.run_ai()
    assert page.ai_banner.property("state") == "error"
    assert "API Key" in page.ai_banner.title.text()