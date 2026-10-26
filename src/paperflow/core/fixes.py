from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from paperflow.core.metadata import M4State
from paperflow.core.structure import StructureResult
from paperflow.llm.review_ai import ReviewFinding


class RenderOverrides(BaseModel):
    model_config = ConfigDict(extra="ignore")

    figure_width: dict[str, float] = Field(default_factory=dict)
    figure_span: dict[str, bool] = Field(default_factory=dict)
    table_span: dict[str, bool] = Field(default_factory=dict)
    page_break_before: list[str] = Field(default_factory=list)
    saved_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class FixAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["figure_width", "figure_span", "table_span", "page_break_before"]
    target: str
    value: float | bool | str
    description: str
    source_finding: str = ""


class FixPlan(BaseModel):
    actions: list[FixAction] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


def build_fix_plan(
    findings: list[ReviewFinding],
    m4: M4State,
    structure: StructureResult,
    overrides: RenderOverrides | None = None,
) -> FixPlan:
    figures = {figure.id: figure for figure in m4.figures}
    tables = {table.id: table for table in m4.tables}
    headings = {
        block.id: block
        for block in structure.document.blocks
        if block.kind == "heading"
    }
    current = overrides or RenderOverrides()
    actions: list[FixAction] = []
    skipped: list[str] = []
    seen: set[tuple[str, str]] = set()

    for finding in findings:
        target = _normalize_target(finding.target)
        kind, ref_id = _split_target(target)
        if not kind or not ref_id:
            skipped.append(f"第 {finding.page} 页 {finding.category}：缺少可定位 target")
            continue
        key = (kind, ref_id)
        if key in seen:
            continue

        if kind == "figure" and ref_id in figures:
            figure = figures[ref_id]
            wants_span = "跨栏" in finding.suggestion or "双栏" in finding.suggestion
            wants_narrower = any(
                word in finding.suggestion or word in finding.evidence
                for word in ("宽度", "缩小", "缩到", "降低", "过宽", "超出", "越界", "溢出")
            )
            if finding.category in {"figure_span", "figure_overflow"} and wants_span:
                actions.append(
                    FixAction(
                        kind="figure_span",
                        target=ref_id,
                        value=True,
                        description=f"{figure.label or ref_id} 改为跨栏",
                        source_finding=f"p{finding.page} {finding.category}",
                    )
                )
                seen.add(key)
            elif finding.category in {"figure_overflow", "figure_width"} and wants_narrower:
                width = current.figure_width.get(ref_id, figure.width_ratio)
                new_width = max(0.55, min(1.0, round(width - 0.15, 2)))
                actions.append(
                    FixAction(
                        kind="figure_width",
                        target=ref_id,
                        value=new_width,
                        description=f"{figure.label or ref_id} 宽度 {width:.2f} → {new_width:.2f}",
                        source_finding=f"p{finding.page} {finding.category}",
                    )
                )
                seen.add(key)
            else:
                skipped.append(
                    f"第 {finding.page} 页 {finding.category}：图片 {ref_id} "
                    "没有明确的缩小/跨栏依据，未自动修改"
                )
        elif kind == "table" and ref_id in tables:
            table = tables[ref_id]
            wants_span = any(
                word in finding.suggestion or word in finding.evidence
                for word in ("跨栏", "双栏", "过窄", "偏窄", "窄于", "未占满")
            )
            if finding.category in {"table_overflow", "table_width"} and wants_span:
                if not table.span_columns:
                    actions.append(
                        FixAction(
                            kind="table_span",
                            target=ref_id,
                            value=True,
                            description=f"{table.label or ref_id} 改为跨栏",
                            source_finding=f"p{finding.page} {finding.category}",
                        )
                    )
                    seen.add(key)
                else:
                    skipped.append(f"第 {finding.page} 页：表格已经跨栏，未自动修改")
            else:
                skipped.append(
                    f"第 {finding.page} 页 {finding.category}：表格 {ref_id} "
                    "没有明确的跨栏依据，未自动修改"
                )
        elif kind == "heading" and ref_id in headings:
            if finding.category in {"heading_orphan", "page_break"}:
                if ref_id not in current.page_break_before:
                    actions.append(
                        FixAction(
                            kind="page_break_before",
                            target=ref_id,
                            value=True,
                            description=f"在“{headings[ref_id].text}”前分页",
                            source_finding=f"p{finding.page} {finding.category}",
                        )
                    )
                    seen.add(key)
                else:
                    skipped.append(f"第 {finding.page} 页：标题前已经分页")
            else:
                skipped.append(
                    f"第 {finding.page} 页 {finding.category}：标题没有安全的自动修复动作"
                )
        else:
            skipped.append(f"第 {finding.page} 页 {finding.category}：target 未匹配到对象")

    return FixPlan(actions=actions, skipped=skipped)


def apply_fix_plan(
    plan: FixPlan,
    overrides: RenderOverrides | None = None,
) -> RenderOverrides:
    result = (overrides or RenderOverrides()).model_copy(deep=True)
    for action in plan.actions:
        if action.kind == "figure_width":
            try:
                width = float(action.value)
            except (TypeError, ValueError):
                continue
            result.figure_width[action.target] = max(0.55, min(1.0, round(width, 2)))
        elif action.kind == "figure_span":
            result.figure_span[action.target] = bool(action.value)
        elif action.kind == "table_span":
            result.table_span[action.target] = bool(action.value)
        elif action.kind == "page_break_before":
            if action.target not in result.page_break_before:
                result.page_break_before.append(action.target)
    return result


def _normalize_target(target: str) -> str:
    return (target or "").strip().replace(" ", "")


def _split_target(target: str) -> tuple[str, str]:
    if not target:
        return "", ""
    match = re.match(
        r"^(figure|fig|table|tab|heading|section):([A-Za-z0-9_\-]+)$",
        target,
        re.IGNORECASE,
    )
    if not match:
        return "", ""
    kind = match.group(1).lower()
    ref_id = match.group(2)
    if kind in {"fig", "figure"}:
        return "figure", ref_id
    if kind in {"tab", "table"}:
        return "table", ref_id
    return "heading", ref_id