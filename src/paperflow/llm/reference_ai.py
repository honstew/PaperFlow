from __future__ import annotations

import json
import logging

import httpx
from openai import OpenAI

from paperflow.core.api import _friendly_error, build_client, is_deepseek_endpoint
from paperflow.core.config import AppSettings
from paperflow.core.references import ReferenceEntry, ReferenceState
from paperflow.llm.ai_prompts import REFERENCE_SYSTEM_PROMPT, build_reference_prompt

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "article",
    "book",
    "inproceedings",
    "phdthesis",
    "report",
    "standard",
    "patent",
    "newspaper",
    "misc",
}


class ReferenceAIError(RuntimeError):
    """User-facing optional AI reference parsing failure."""


def parse_references_with_ai(
    settings: AppSettings,
    api_key: str,
    state: ReferenceState,
) -> ReferenceState:
    api_key = (api_key or "").strip()
    if not api_key:
        raise ReferenceAIError("请先在“环境与 API”填写 API Key")
    if not state.entries:
        raise ReferenceAIError("没有可解析的参考文献条目")

    source = [
        {"id": entry.id, "text": entry.original_text}
        for entry in state.entries
    ]
    logger.info("Optional AI reference parse: entries=%d", len(source))
    client: OpenAI | None = None
    http_client: httpx.Client | None = None
    try:
        client, http_client = build_client(settings, api_key)
        request: dict[str, object] = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": REFERENCE_SYSTEM_PROMPT},
                {"role": "user", "content": build_reference_prompt(source)},
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if is_deepseek_endpoint(settings.base_url):
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        response = client.chat.completions.create(**request)
        content = ""
        try:
            content = response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            content = ""
        if not content.strip():
            raise ReferenceAIError("AI 返回空内容，未修改本地参考文献")
        try:
            payload = json.loads(_strip_code_fence(content))
        except json.JSONDecodeError as exc:
            raise ReferenceAIError("AI 返回的内容不是合法 JSON") from exc
        return apply_reference_payload(state, payload)
    except ReferenceAIError:
        raise
    except Exception as exc:
        logger.exception("Optional AI reference parse failed")
        raise ReferenceAIError(f"AI 解析失败：{_friendly_error(exc)}") from exc
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("Failed to close OpenAI client", exc_info=True)
        if http_client is not None:
            try:
                http_client.close()
            except Exception:
                logger.debug("Failed to close HTTP client", exc_info=True)


def apply_reference_payload(
    state: ReferenceState,
    payload: object,
) -> ReferenceState:
    if not isinstance(payload, dict):
        raise ReferenceAIError("AI 返回的 JSON 顶层必须是对象")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ReferenceAIError("AI 返回缺少 entries 数组")
    by_id = {entry.id: entry for entry in state.entries}
    updated: list[ReferenceEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        ref_id = str(raw.get("id") or "").strip()
        old = by_id.get(ref_id)
        if old is None:
            continue
        entry_type = str(raw.get("type") or old.type).strip()
        if entry_type not in ALLOWED_TYPES:
            entry_type = old.type
        authors = raw.get("authors")
        if not isinstance(authors, list):
            authors = old.authors
        authors = [str(item).strip() for item in authors if str(item).strip()]
        language = str(raw.get("language") or old.language).strip()
        if language not in {"chinese", "english"}:
            language = old.language
        try:
            confidence = float(raw.get("confidence", old.confidence))
        except (TypeError, ValueError):
            confidence = old.confidence
        confidence = max(0.0, min(1.0, confidence))
        missing = raw.get("missing_fields")
        if not isinstance(missing, list):
            missing = old.missing_fields
        updated.append(
            old.model_copy(
                update={
                    "type": entry_type,
                    "authors": authors,
                    "title": _prefer(raw.get("title"), old.title),
                    "journal": _prefer(raw.get("journal"), old.journal),
                    "booktitle": _prefer(raw.get("booktitle"), old.booktitle),
                    "publisher": _prefer(raw.get("publisher"), old.publisher),
                    "address": _prefer(raw.get("address"), old.address),
                    "year": _prefer(raw.get("year"), old.year),
                    "volume": _prefer(raw.get("volume"), old.volume),
                    "number": _prefer(raw.get("number"), old.number),
                    "pages": _prefer(raw.get("pages"), old.pages),
                    "doi": _prefer(raw.get("doi"), old.doi),
                    "url": _prefer(raw.get("url"), old.url),
                    "language": language,
                    "confidence": confidence,
                    "missing_fields": [str(item) for item in missing],
                    "status": "pending",
                }
            )
        )
    if not updated:
        raise ReferenceAIError("AI 没有返回可识别的条目，未修改本地参考文献")
    seen = {entry.id for entry in updated}
    updated.extend(entry for entry in state.entries if entry.id not in seen)
    order = {entry.id: index for index, entry in enumerate(state.entries)}
    updated.sort(key=lambda item: order.get(item.id, 9999))
    return ReferenceState(entries=updated, source="ai")


def _prefer(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text