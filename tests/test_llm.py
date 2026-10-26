from __future__ import annotations

import pytest

from paperflow.llm.parser import StructureParseError, parse_structure_json


def test_parse_structure_json_with_fence() -> None:
    content = """```json
{"metadata": {"title": "测试"}, "blocks": [
  {"block_id": "B0001", "role": "title", "heading_level": null, "confidence": 0.99}
]}
```"""
    parsed = parse_structure_json(content)
    assert parsed.metadata.title == "测试"
    assert parsed.blocks[0].role == "title"
    assert parsed.blocks[0].heading_level is None


def test_parse_structure_json_rejects_invalid() -> None:
    with pytest.raises(StructureParseError):
        parse_structure_json("")
    with pytest.raises(StructureParseError):
        parse_structure_json("not json")
    with pytest.raises(StructureParseError):
        parse_structure_json('{"blocks": [{"block_id": "B1", "role": "bogus"}]}')


def test_missing_key_is_reported() -> None:
    from paperflow.core.config import AppSettings
    from paperflow.core.document import Document
    from paperflow.llm.client import StructureError, extract_structure

    with pytest.raises(StructureError, match="API Key"):
        extract_structure(AppSettings(), "", Document())