from __future__ import annotations

import logging
import time

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from paperflow.core.api import (
    _friendly_error,
    _status_message,
    build_client,
    is_deepseek_endpoint,
)
from paperflow.core.config import AppSettings
from paperflow.core.document import Document
from paperflow.core.structure import (
    StructureResult,
    StructureValidationError,
    apply_structure_response,
)
from paperflow.llm.parser import StructureParseError, parse_structure_json
from paperflow.llm.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 120_000


class StructureError(RuntimeError):
    """User-facing structure recognition failure."""


def extract_structure(
    settings: AppSettings,
    api_key: str,
    document: Document,
) -> StructureResult:
    api_key = (api_key or "").strip()
    if not api_key:
        raise StructureError("请先在“环境与 API”填写并保存 API Key")
    if not document.blocks:
        raise StructureError("当前文档没有内容块，请先导入论文")
    text_chars = sum(len(block.text) for block in document.blocks)
    if text_chars > MAX_PROMPT_CHARS:
        raise StructureError(
            f"文档较大（约 {text_chars:,} 字符），M3 首版暂一次处理；"
            "请先拆分文档或等待分块识别。"
        )

    logger.info(
        "Structure request: base_url=%s model=%s blocks=%d chars=%d",
        settings.base_url,
        settings.model,
        len(document.blocks),
        text_chars,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(document)},
    ]
    last_error = ""
    started = time.perf_counter()
    client: OpenAI | None = None
    http_client: httpx.Client | None = None
    try:
        client, http_client = build_client(settings, api_key)
        for attempt in range(2):
            try:
                response = _request(client, settings, messages)
            except BadRequestError as exc:
                raise StructureError(f"请求参数不合法：{_friendly_error(exc)}") from exc
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            request_id = str(
                getattr(response, "_request_id", None) or getattr(response, "id", "") or ""
            )
            try:
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = getattr(choice, "finish_reason", "") or ""
            except (IndexError, AttributeError):
                content = ""
                finish_reason = ""
            if not content.strip():
                last_error = "模型返回空内容"
                logger.warning("Structure attempt %d returned empty content", attempt + 1)
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": "上一次没有返回内容。请只返回符合要求的 JSON 对象。",
                        }
                    )
                    continue
                break
            if finish_reason == "length":
                last_error = "模型输出被截断"
                logger.warning("Structure output truncated")
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": "上一次输出被截断。这次请压缩 note，只保留必要字段，确保 JSON 完整。",
                        }
                    )
                    continue
                break
            try:
                parsed = parse_structure_json(content)
                result = apply_structure_response(
                    document,
                    parsed,
                    source="ai",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    request_id=request_id,
                )
            except (StructureParseError, StructureValidationError) as exc:
                last_error = str(exc)
                logger.warning("Structure attempt %d invalid: %s", attempt + 1, exc)
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"上一次输出未通过校验：{exc}。"
                                "请重新输出完整 JSON，blocks 必须覆盖每个输入 block_id，"
                                "且不能新增或遗漏。"
                            ),
                        }
                    )
                    continue
                break
            logger.info(
                "Structure result: blocks=%d tokens=%s/%s elapsed=%.2fs",
                len(result.blocks),
                prompt_tokens,
                completion_tokens,
                time.perf_counter() - started,
            )
            return result
        raise StructureError(f"结构识别失败：{last_error or '模型未返回可用结果'}")
    except AuthenticationError as exc:
        raise StructureError("API Key 无效或已失效，请检查后重试") from exc
    except PermissionDeniedError as exc:
        raise StructureError("当前 Key 无权访问该模型，请检查模型名称与账户权限") from exc
    except RateLimitError as exc:
        raise StructureError("请求过于频繁或并发受限，请稍后重试") from exc
    except APITimeoutError as exc:
        raise StructureError("请求超时，请检查网络或调大超时时间") from exc
    except APIConnectionError as exc:
        raise StructureError("无法连接 API，请检查网络、代理和 Base URL") from exc
    except APIStatusError as exc:
        status = getattr(exc, "status_code", 0)
        raise StructureError(_status_message(status, exc)) from exc
    except OpenAIError as exc:
        logger.exception("OpenAI SDK error during structure recognition")
        raise StructureError(f"API 调用失败：{_friendly_error(exc)}") from exc
    except StructureError:
        raise
    except Exception as exc:  # defensive
        logger.exception("Unexpected error during structure recognition")
        raise StructureError(f"结构识别失败：{_friendly_error(exc)}") from exc
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


def _request(client: OpenAI, settings: AppSettings, messages: list[dict[str, str]]):
    request: dict[str, object] = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 8192,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    if is_deepseek_endpoint(settings.base_url):
        request["extra_body"] = {"thinking": {"type": "disabled"}}
    return client.chat.completions.create(**request)