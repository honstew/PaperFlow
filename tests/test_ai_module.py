from __future__ import annotations

from pathlib import Path

from paperflow.core.config import AppSettings
from paperflow.core.metadata import build_m4_state
from paperflow.core.references import parse_references
from paperflow.core.structure import build_local_structure
from paperflow.ingest import import_document
from paperflow.llm.ai_prompts import PDF_REVIEW_SYSTEM_PROMPT, REFERENCE_SYSTEM_PROMPT
from paperflow.llm.reference_ai import apply_reference_payload
from paperflow.llm.review_ai import validate_review_payload
from paperflow.ui.build_page import BuildPage
from paperflow.ui.references_page import ReferencesPage


def _context(tmp_path: Path):
    imported = import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    )
    structure = build_local_structure(imported.document)
    return imported, structure, build_m4_state(imported, structure)


def test_prompts_are_strict_and_read_only() -> None:
    assert "不能猜测" in REFERENCE_SYSTEM_PROMPT
    assert "只输出 JSON" in REFERENCE_SYSTEM_PROMPT
    assert "不改写" in PDF_REVIEW_SYSTEM_PROMPT
    assert "只输出 JSON" in PDF_REVIEW_SYSTEM_PROMPT


def test_apply_reference_payload_preserves_unmentioned_fields(tmp_path: Path) -> None:
    imported, structure, _ = _context(tmp_path)
    state = parse_references(structure.document, structure)
    first = state.entries[0]
    payload = {
        "entries": [
            {
                "id": first.id,
                "type": "article",
                "authors": ["张三"],
                "title": "AI 不补造的题名",
                "year": "2026",
                "volume": "46",
                "confidence": 0.9,
            }
        ]
    }
    updated = apply_reference_payload(state, payload)
    item = updated.entries[0]
    assert item.title == "AI 不补造的题名"
    assert item.volume == "46"
    assert item.number == "3"
    assert item.status == "pending"
    assert len(updated.entries) == len(state.entries)


def test_validate_review_payload_drops_invalid_pages() -> None:
    findings = validate_review_payload(
        {
            "findings": [
                {"page": 1, "severity": "major", "evidence": "越界", "suggestion": "缩宽"},
                {"page": 99, "severity": "major", "evidence": "不存在", "suggestion": "忽略"},
                {"page": 2, "severity": "minor", "evidence": "", "suggestion": ""},
            ]
        },
        page_count=3,
    )
    assert len(findings) == 1
    assert findings[0].page == 1
    assert findings[0].severity == "major"


def test_ai_buttons_require_key(qtbot, tmp_path: Path) -> None:
    imported, structure, m4 = _context(tmp_path)
    references = parse_references(structure.document, structure)
    page = ReferencesPage()
    qtbot.addWidget(page)
    page.set_context(imported, structure, references)
    page.set_ai_context(AppSettings(), lambda: "")
    assert page.ai_button.isEnabled() is False
    page.set_ai_context(AppSettings(), lambda: "sk-test")
    assert page.ai_button.isEnabled() is True

    build = BuildPage()
    qtbot.addWidget(build)
    build.set_ai_context(AppSettings(), lambda: "sk-test")
    assert build.ai_review_button.isEnabled() is False
    build.set_context(imported, structure, m4, references, _layout())
    assert build.ai_review_button.isEnabled() is False


def _layout():
    from paperflow.core.layout import LayoutSettings

    return LayoutSettings()