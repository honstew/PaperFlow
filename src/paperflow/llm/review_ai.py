from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from paperflow.core.api import _friendly_error, build_client, is_deepseek_endpoint
from paperflow.core.config import AppSettings
from paperflow.llm.ai_prompts import PDF_REVIEW_SYSTEM_PROMPT, build_pdf_review_prompt

logger = logging.getLogger(__name__)

MAX_REVIEW_PAGES = 20
SEVERITIES = {"major", "minor", "info"}


class ReviewAIError(RuntimeError):
    """User-facing optional visual review failure."""


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int
    severity: str = "minor"
    category: str = "other"
    evidence: str = ""
    suggestion: str = ""
    target: str = ""
    confidence: float = 0.5
    auto_fixable: bool = False


@dataclass(slots=True)
class ReviewPage:
    page_number: int
    png: bytes
    text: str = ""


@dataclass(slots=True)
class AIReviewResult:
    findings: list[ReviewFinding] = field(default_factory=list)
    page_count: int = 0
    raw: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def render_pdf_pages(pdf_path: Path, *, max_pages: int = MAX_REVIEW_PAGES) -> list[ReviewPage]:
    pages: list[ReviewPage] = []
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        count = min(len(document), max_pages)
        for index in range(count):
            page = document[index]
            bitmap = page.render(scale=1.4)
            pil = bitmap.to_pil()
            buffer = io.BytesIO()
            pil.save(buffer, format="PNG")
            try:
                text = page.get_textpage().get_text_bounded()
            except Exception:
                text = ""
            pages.append(
                ReviewPage(
                    page_number=index + 1,
                    png=buffer.getvalue(),
                    text=text,
                )
            )
    finally:
        document.close()
    return pages


def review_pdf_with_ai(
    settings: AppSettings,
    api_key: str,
    pdf_path: Path,
    *,
    layout_note: str = "",
    target_catalog: str = "",
    max_pages: int = MAX_REVIEW_PAGES,
) -> AIReviewResult:
    api_key = (api_key or "").strip()
    if not api_key:
        raise ReviewAIError("请先在“环境与 API”填写 API Key")
    pages = render_pdf_pages(pdf_path, max_pages=max_pages)
    if not pages:
        raise ReviewAIError("PDF 没有可审阅页面")

    prompt = build_pdf_review_prompt(
        len(pages),
        [page.text for page in pages],
        target_catalog=target_catalog,
    )
    if layout_note:
        prompt += f"\n\n当前版式参数：{layout_note}"
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for page in pages:
        encoded = base64.b64encode(page.png).decode("ascii")
        content.append(
            {
                "type": "text",
                "text": f"下面是第 {page.page_number} 页：",
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )

    logger.info("Optional AI visual review: pages=%d", len(pages))
    client: OpenAI | None = None
    http_client: httpx.Client | None = None
    raw = ""
    try:
        client, http_client = build_client(settings, api_key)
        request: dict[str, object] = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": PDF_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if is_deepseek_endpoint(settings.base_url):
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        response = client.chat.completions.create(**request)
        raw = ""
        try:
            raw = response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            raw = ""
        if not raw.strip():
            raise ReviewAIError("AI 返回空内容，未生成审阅结果")
        payload = json.loads(_strip_code_fence(raw))
        findings = validate_review_payload(payload, page_count=len(pages))
        usage = getattr(response, "usage", None)
        return AIReviewResult(
            findings=findings,
            page_count=len(pages),
            raw=raw,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
    except ReviewAIError:
        raise
    except json.JSONDecodeError as exc:
        raise ReviewAIError("AI 返回的内容不是合法 JSON") from exc
    except Exception as exc:
        logger.exception("Optional AI visual review failed")
        raise ReviewAIError(f"AI 审阅失败：{_friendly_error(exc)}") from exc
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


def validate_review_payload(payload: object, *, page_count: int) -> list[ReviewFinding]:
    if not isinstance(payload, dict):
        raise ReviewAIError("AI 返回的 JSON 顶层必须是对象")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise ReviewAIError("AI 返回缺少 findings 数组")
    findings: list[ReviewFinding] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        try:
            page = int(raw.get("page", 0))
        except (TypeError, ValueError):
            continue
        if page < 1 or page > page_count:
            continue
        severity = str(raw.get("severity") or "minor").lower()
        if severity not in SEVERITIES:
            severity = "minor"
        evidence = str(raw.get("evidence") or "").strip()
        suggestion = str(raw.get("suggestion") or "").strip()
        if not evidence and not suggestion:
            continue
        try:
            confidence = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        findings.append(
            ReviewFinding(
                page=page,
                severity=severity,
                category=str(raw.get("category") or "other").strip() or "other",
                evidence=evidence,
                suggestion=suggestion,
                target=str(raw.get("target") or "").strip(),
                confidence=max(0.0, min(1.0, confidence)),
                auto_fixable=bool(raw.get("auto_fixable", False)),
            )
        )
    findings.sort(key=lambda item: (item.page, {"major": 0, "minor": 1, "info": 2}.get(item.severity, 3)))
    return findings


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