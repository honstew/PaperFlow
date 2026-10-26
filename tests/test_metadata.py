from __future__ import annotations

from pathlib import Path

from paperflow.core.metadata import build_m4_state
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document


def _build(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    return imported, structure, build_m4_state(imported, structure)


def test_build_m4_state_prefills_and_consumes(tmp_path: Path) -> None:
    _imported, _structure, state = _build(tmp_path)

    assert state.metadata.title.value == "面向高校论文的自动排版流程设计与实现"
    assert [author.name for author in state.metadata.authors] == ["张三", "李四"]
    assert state.metadata.affiliations[0].name.startswith("某某大学")
    assert len(state.figures) == 1
    assert len(state.tables) == 1
    assert {"B0001", "B0002", "B0003", "B0004", "B0005"}.issubset(
        set(state.metadata.consumed_block_ids)
    )
    assert state.metadata.conflicts == []


def test_metadata_conflict_and_keep_form(tmp_path: Path) -> None:
    _imported, _structure, state = _build(tmp_path)
    metadata = state.metadata
    metadata.title.value = "用户修改后的题名"
    conflicts = metadata.detect_conflicts()

    assert any(conflict.field == "title" for conflict in conflicts)
    assert len(metadata.unresolved_conflicts) >= 1

    metadata.mark_form_priority()
    metadata.detect_conflicts()
    title_conflict = next(
        conflict for conflict in metadata.conflicts if conflict.field == "title"
    )
    assert title_conflict.resolved is True


def test_fund_off_conflict_requires_confirmation(tmp_path: Path) -> None:
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

    assert state.metadata.body_funds
    state.metadata.fund_enabled = False
    conflicts = state.metadata.detect_conflicts()
    assert any(conflict.kind == "fund_off" for conflict in conflicts)