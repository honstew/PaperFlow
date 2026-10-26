from __future__ import annotations

from pathlib import Path

import pytest

from paperflow.core.document import Document
from paperflow.core.structure import (
    StructureBlock,
    StructureMetadata,
    StructureResponse,
    StructureValidationError,
    apply_structure_response,
    build_local_structure,
    validate_coverage,
)
from paperflow.ingest import import_document


def _document(tmp_path: Path) -> Document:
    return import_document(
        Path("examples/demo-paper.md"),
        projects_dir=tmp_path / "projects",
    ).document


def test_local_structure_extracts_metadata_and_sections(tmp_path: Path) -> None:
    result = build_local_structure(_document(tmp_path))

    assert result.source == "local"
    assert result.metadata.title == "面向高校论文的自动排版流程设计与实现"
    assert result.metadata.authors == ["张三", "李四"]
    assert result.metadata.keywords[0] == "论文排版"
    assert len(result.blocks) == 29
    assert sum(1 for item in result.blocks if item.role == "heading") == 8
    assert result.sections


def test_coverage_rejects_missing_and_duplicate_blocks(tmp_path: Path) -> None:
    document = _document(tmp_path)
    missing = StructureResponse(
        metadata=StructureMetadata(title=document.title),
        blocks=[
            StructureBlock(block_id=block.id, role="paragraph")
            for block in document.blocks[1:]
        ],
    )
    with pytest.raises(StructureValidationError, match="缺少"):
        validate_coverage(document, missing)

    duplicate = StructureResponse(
        blocks=[
            StructureBlock(block_id=document.blocks[0].id, role="paragraph"),
            *[
                StructureBlock(block_id=block.id, role="paragraph")
                for block in document.blocks
            ],
        ]
    )
    with pytest.raises(StructureValidationError, match="重复"):
        validate_coverage(document, duplicate)


def test_apply_structure_updates_roles_and_sections(tmp_path: Path) -> None:
    document = _document(tmp_path)
    blocks = [
        StructureBlock(
            block_id=block.id,
            role="heading" if block.id == "B0006" else "paragraph",
            heading_level=1 if block.id == "B0006" else None,
            confidence=0.9,
        )
        for block in document.blocks
    ]
    result = apply_structure_response(
        document,
        StructureResponse(metadata=StructureMetadata(title="新题名"), blocks=blocks),
    )

    assert result.source == "ai"
    assert result.metadata.title == "新题名"
    assert next(item for item in result.document.blocks if item.id == "B0006").heading_level == 1
    assert result.sections


def test_structure_block_normalizes_heading_level() -> None:
    heading = StructureBlock(block_id="B1", role="heading", heading_level=None)
    paragraph = StructureBlock(block_id="B2", role="paragraph", heading_level=3)

    assert heading.heading_level == 1
    assert paragraph.heading_level is None