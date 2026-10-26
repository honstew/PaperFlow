from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

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

from paperflow.core.config import DEFAULT_BASE_URL, AppSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    ok: bool
    message: str
    model: str = ""
    latency_ms: int = 0
    request_id: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def usage_text(self) -> str:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return ""
        return f"输入 {self.prompt_tokens or 0} / 输出 {self.completion_tokens or 0} tokens"


def is_deepseek_endpoint(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def build_client(
    settings: AppSettings,
    api_key: str,
    *,
    timeout_s: float | None = None,
) -> tuple[OpenAI, httpx.Client | None]:
    timeout = float(timeout_s if timeout_s is not None else settings.timeout_s)
    http_client = None
    if settings.proxy:
        http_client = httpx.Client(proxy=settings.proxy, timeout=httpx.Timeout(timeout))
    client = OpenAI(
        api_key=api_key,
        base_url=settings.base_url or DEFAULT_BASE_URL,
        timeout=timeout,
        max_retries=0,
        http_client=http_client,
    )
    return client, http_client


def test_connection(settings: AppSettings, api_key: str) -> ConnectionResult:
    """Perform a tiny, low-cost chat request.

    DeepSeek enables thinking mode by default, so the probe explicitly disables
    it for this endpoint.  Other OpenAI-compatible endpoints do not receive the
    DeepSeek-only ``extra_body`` field.
    """

    api_key = api_key.strip()
    if not api_key:
        return ConnectionResult(False, "请先填写 API Key")

    logger.info(
        "Testing API connection: base_url=%s model=%s",
        settings.base_url,
        settings.model,
    )
    started = time.perf_counter()
    client: OpenAI | None = None
    http_client: httpx.Client | None = None
    try:
        client, http_client = build_client(settings, api_key)
        request: dict[str, object] = {
            "model": settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a connection probe. Reply with exactly OK.",
                },
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            "max_tokens": 8,
            "stream": False,
        }
        if is_deepseek_endpoint(settings.base_url):
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        response = client.chat.completions.create(**request)
        latency = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        request_id = str(
            getattr(response, "_request_id", None) or getattr(response, "id", "") or ""
        )
        content = ""
        try:
            content = response.choices[0].message.content or ""
        except (IndexError, AttributeError):
            content = ""
        suffix = " · 返回为空" if not content.strip() else ""
        return ConnectionResult(
            ok=True,
            message=f"连接正常{suffix}",
            model=settings.model,
            latency_ms=latency,
            request_id=request_id,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )
    except AuthenticationError:
        return ConnectionResult(False, "API Key 无效或已失效，请检查后重试")
    except PermissionDeniedError:
        return ConnectionResult(False, "当前 Key 无权访问该模型，请检查模型名称与账户权限")
    except RateLimitError:
        return ConnectionResult(False, "请求过于频繁或并发受限，请稍后重试")
    except BadRequestError as exc:
        return ConnectionResult(False, f"请求参数不合法：{_friendly_error(exc)}")
    except APITimeoutError:
        return ConnectionResult(False, "请求超时，请检查网络或调大超时时间")
    except APIConnectionError:
        return ConnectionResult(False, "无法连接 API，请检查网络、代理和 Base URL")
    except APIStatusError as exc:
        status = getattr(exc, "status_code", 0)
        return ConnectionResult(False, _status_message(status, exc))
    except OpenAIError as exc:
        logger.exception("OpenAI SDK error during connection test")
        return ConnectionResult(False, f"API 调用失败：{_friendly_error(exc)}")
    except Exception as exc:  # defensive: never let a worker crash the UI
        logger.exception("Unexpected error during connection test")
        return ConnectionResult(False, f"连接测试失败：{_friendly_error(exc)}")
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


def _status_message(status: int, exc: BaseException) -> str:
    if status == 401:
        return "API Key 无效或已失效，请检查后重试"
    if status == 402:
        return "账户余额不足，请充值或更换 API Key"
    if status == 403:
        return "无权访问该模型，请检查账户权限"
    if status == 404:
        return "接口地址不存在，请检查 Base URL 是否填写正确"
    if status == 422:
        return f"请求参数不合法：{_friendly_error(exc)}"
    if status == 429:
        return "请求过于频繁，请稍后重试"
    if 500 <= status < 600:
        return f"服务端暂时不可用（HTTP {status}），请稍后重试"
    return f"API 返回错误（HTTP {status}）：{_friendly_error(exc)}"


def _friendly_error(exc: BaseException) -> str:
    text = str(exc).strip().replace("\n", " ")
    if len(text) > 300:
        text = text[:297] + "..."
    return text or exc.__class__.__name__