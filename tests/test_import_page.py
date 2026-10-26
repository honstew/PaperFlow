from __future__ import annotations

from pathlib import Path

from paperflow.ingest import import_document
from paperflow.ui.import_page import ImportPage


def _write_sample(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    md = source / "sample.md"
    md.write_text(
        "# 测试论文\n\n"
        "摘要：本文测试导入。\n\n"
        "## 1 引言\n\n"
        "如图1所示。\n\n"
        "![图1 流程图](fig1.png)\n\n"
        "表1 数据\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    return md


def test_import_page_populates_summary_and_tables(qtbot, tmp_path: Path) -> None:
    md = _write_sample(tmp_path)
    result = import_document(md, projects_dir=tmp_path / "projects")
    page = ImportPage(tmp_path / "projects")
    qtbot.addWidget(page)
    page.show()

    page._on_imported(result)
    qtbot.wait(20)

    assert page.block_table.rowCount() == result.summary.block_count
    assert page.asset_table.rowCount() == 2
    assert page.kpi_blocks.value.text() == str(result.summary.block_count)
    assert page.file_name.text() == "sample.md"
    assert page.result_card.isHidden() is False
    assert page.last_result is result


def test_import_page_runs_import_in_background(qtbot, tmp_path: Path) -> None:
    md = _write_sample(tmp_path)
    page = ImportPage(tmp_path / "projects")
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.import_completed, timeout=5000) as blocker:
        page._start_import(md)

    result = blocker.args[0]
    assert result.summary.block_count > 0
    assert page.last_result is result
    qtbot.wait(30)
    assert page._busy is False