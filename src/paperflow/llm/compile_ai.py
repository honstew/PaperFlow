from __future__ import annotations

import json
import logging

import httpx
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from paperflow.core.api import _friendly_error, build_client, is_deepseek_endpoint
from paperflow.core.config import AppSettings
from paperflow.llm.ai_prompts import COMPILE_FIX_SYSTEM_PROMPT, build_compile_fix_prompt

logger = logging.getLogger(__name__)


class CompilePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    search: str
    replace: str
    reason: str = ""


class CompileFixResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    diagnosis: str = ""
    patches: list[CompilePatch] = Field(default_factory=list)
    confidence: float = 0.5
    raw: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class CompileAIError(RuntimeError):
    """User-facing optional compile-fix failure."""


def analyze_compile_failure(
    settings: AppSettings,
    api_key: str,
    compile_log: str,
    tex: str,
) -> CompileFixResult:
    api_key = (api_key or "").strip()
    if not api_key:
        raise CompileAIError("请先在“环境与 API”填写 API Key")
    if not compile_log.strip():
        raise CompileAIError("没有可分析的编译日志")
    if not tex.strip():
        raise CompileAIError("没有可分析的 main.tex")

    client: OpenAI | None = None
    http_client: httpx.Client | None = None
    try:
        client, http_client = build_client(settings, api_key)
        request: dict[str, object] = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": COMPILE_FIX_SYSTEM_PROMPT},
                {"role": "user", "content": build_compile_fix_prompt(compile_log, tex)},
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
            raise CompileAIError("AI 返回空内容")
        payload = json.loads(_strip_code_fence(content))
        if not isinstance(payload, dict):
            raise CompileAIError("AI 返回的 JSON 顶层必须是对象")
        raw_patches = payload.get("patches", [])
        if not isinstance(raw_patches, list):
            raw_patches = []
        patches = []
        for raw in raw_patches:
            if not isinstance(raw, dict):
                continue
            search = str(raw.get("search") or "")
            replace = str(raw.get("replace") or "")
            if not search.strip():
                continue
            patches.append(
                CompilePatch(
                    search=search,
                    replace=replace,
                    reason=str(raw.get("reason") or ""),
                )
            )
        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        usage = getattr(response, "usage", None)
        return CompileFixResult(
            diagnosis=str(payload.get("diagnosis") or "").strip(),
            patches=patches[:8],
            confidence=max(0.0, min(1.0, confidence)),
            raw=content,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
    except CompileAIError:
        raise
    except json.JSONDecodeError as exc:
        raise CompileAIError("AI 返回的内容不是合法 JSON") from exc
    except Exception as exc:
        logger.exception("Optional AI compile fix failed")
        raise CompileAIError(f"AI 编译修复分析失败：{_friendly_error(exc)}") from exc
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


def apply_compile_patches(tex: str, patches: list[CompilePatch]) -> tuple[str, list[str]]:
    result = tex
    applied: list[str] = []
    for patch in patches[:8]:
        search = patch.search
        if not search or search not in result:
            raise CompileAIError("修改片段没有在 main.tex 中找到，已拒绝应用")
        if result.count(search) != 1:
            raise CompileAIError("修改片段在 main.tex 中不唯一，已拒绝应用")
        lower = patch.replace.lower()
        if any(
            token in lower
            for token in (r"\write18", r"\input", r"\include", r"\catcode")
        ):
            raise CompileAIError("AI 修改包含不允许的外部命令，已拒绝应用")
        result = result.replace(search, patch.replace, 1)
        applied.append(patch.reason or "修改片段")
    return result, applied


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