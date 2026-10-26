from __future__ import annotations

from pathlib import Path

from paperflow.core.fixes import (
    RenderOverrides,
    apply_fix_plan,
    build_fix_plan,
)
from paperflow.core.layout import LayoutSettings
from paperflow.core.metadata import build_m4_state
from paperflow.core.references import parse_references
from paperflow.core.render import render_project
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document
from paperflow.llm.review_ai import ReviewFinding


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    m4 = build_m4_state(imported, structure)
    references = parse_references(structure.document, structure)
    return imported, structure, m4, references


def test_figure_width_fix_is_bounded_and_rendered(tmp_path: Path) -> None:
    imported, structure, m4, references = _context(tmp_path)
    figure = m4.figures[0]
    finding = ReviewFinding(
        page=1,
        severity="major",
        category="figure_overflow",
        evidence="右侧越界",
        suggestion="缩小宽度",
        target=f"figure:{figure.id}",
        confidence=0.9,
    )
    plan = build_fix_plan([finding], m4, structure)
    assert len(plan.actions) == 1
    overrides = apply_fix_plan(plan)
    assert overrides.figure_width[figure.id] == 0.65

    result = render_project(
        Path(imported.project_dir),
        imported,
        structure,
        m4,
        references,
        LayoutSettings(),
        overrides,
    )
    assert "width=0.65\\linewidth" in result.tex_path.read_text(encoding="utf-8")


def test_table_span_and_heading_break_actions(tmp_path: Path) -> None:
    imported, structure, m4, references = _context(tmp_path)
    table = m4.tables[0]
    heading = next(
        block for block in structure.document.blocks if block.kind == "heading"
    )
    findings = [
        ReviewFinding(
            page=2,
            severity="minor",
            category="table_overflow",
            evidence="表格偏窄",
            suggestion="改为跨栏",
            target=f"table:{table.id}",
        ),
        ReviewFinding(
            page=2,
            severity="major",
            category="heading_orphan",
            evidence="标题在页底",
            suggestion="标题前分页",
            target=f"heading:{heading.id}",
        ),
    ]
    plan = build_fix_plan(findings, m4, structure)
    overrides = apply_fix_plan(plan)
    assert overrides.table_span[table.id] is True
    assert heading.id in overrides.page_break_before

    result = render_project(
        Path(imported.project_dir),
        imported,
        structure,
        m4,
        references,
        LayoutSettings(),
        overrides,
    )
    tex = result.tex_path.read_text(encoding="utf-8")
    assert "\\begin{table*}" in tex
    assert "\\clearpage" in tex


def test_clipping_without_width_evidence_is_skipped(tmp_path: Path) -> None:
    _, structure, m4, _ = _context(tmp_path)
    figure = m4.figures[0]
    finding = ReviewFinding(
        page=1,
        severity="minor",
        category="figure_overflow",
        evidence="图片裁剪范围不完整，箭头中断",
        suggestion="检查图片裁剪范围，确保图形完整",
        target=f"figure:{figure.id}",
    )
    plan = build_fix_plan([finding], m4, structure)
    assert not plan.actions
    assert "没有明确" in plan.skipped[0]


def test_missing_or_unsupported_target_is_skipped(tmp_path: Path) -> None:
    _, structure, m4, _ = _context(tmp_path)
    finding = ReviewFinding(
        page=1,
        severity="minor",
        category="figure_overflow",
        evidence="越界",
        suggestion="缩小",
        target="",
    )
    plan = build_fix_plan([finding], m4, structure)
    assert not plan.actions
    assert plan.skipped


def test_apply_fix_plan_does_not_mutate_original(tmp_path: Path) -> None:
    _, structure, m4, _ = _context(tmp_path)
    original = RenderOverrides(figure_width={"f001": 0.8})
    plan = build_fix_plan([], m4, structure)
    updated = apply_fix_plan(plan, original)
    assert original.figure_width == {"f001": 0.8}
    assert updated.figure_width == {"f001": 0.8}