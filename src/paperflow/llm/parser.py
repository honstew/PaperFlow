from __future__ import annotations

import json
import re

from paperflow.core.structure import StructureResponse


class StructureParseError(ValueError):
    """The model output was not valid structure JSON."""


def parse_structure_json(content: str) -> StructureResponse:
    text = (content or "").strip()
    if not text:
        raise StructureParseError("模型返回空内容")
    text = _strip_fence(text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise StructureParseError("模型返回内容中没有 JSON 对象")
    payload = text[start : end + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StructureParseError(f"JSON 解析失败：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise StructureParseError("JSON 顶层必须是对象")
    try:
        return StructureResponse.model_validate(data)
    except Exception as exc:
        raise StructureParseError(f"结构字段校验失败：{exc}") from exc


def _strip_fence(text: str) -> str:
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text