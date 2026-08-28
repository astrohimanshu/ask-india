"""LLM access: one JSON-contract call, validated into a Pydantic model.

`LiteLLMClient` is the real backend (Ollama in development, a hosted provider in production — the
model id in settings decides). `ScriptedLLM` replays canned replies so every graph node can be
unit-tested without a model.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol

import litellm
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from pydantic import BaseModel, ValidationError

from askindia_agents import tracing
from askindia_agents.settings import get_settings

litellm.suppress_debug_info = True

#: Failures worth trying again: the provider is throttling us or briefly unreachable. A contract
#: violation or a bad request is not here — retrying those just spends quota on the same answer.
RETRYABLE: tuple[type[Exception], ...] = (
    RateLimitError,
    ServiceUnavailableError,
    InternalServerError,
    APIConnectionError,
    Timeout,
)

#: Groq states the wait inside the error message ("Please try again in 787.5ms"); other providers
#: use a `retry_after` attribute. Both are preferred over guessing.
_RETRY_AFTER_TEXT = re.compile(r"try again in\s+([0-9.]+)\s*(ms|s)\b", re.IGNORECASE)


class ContractViolationError(ValueError):
    """The model did not return the requested JSON shape."""


class JSONCompleter(Protocol):
    def complete_json[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, str] | None = None,
    ) -> T: ...


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_contract[T: BaseModel](content: str, schema: type[T]) -> T:
    try:
        payload = json.loads(_strip_fences(content))
    except json.JSONDecodeError as e:
        raise ContractViolationError(f"model reply is not JSON: {content[:200]!r}") from e
    try:
        return schema.model_validate(payload)
    except ValidationError as e:
        raise ContractViolationError(f"model reply violates {schema.__name__}: {e}") from e


def retry_delay(exc: Exception, attempt: int, cap_seconds: float) -> float:
    """Seconds to wait before retry `attempt` (1-based), never more than `cap_seconds`.

    A provider that tells us how long to wait is believed; otherwise back off exponentially. The
    small constant added to a stated wait covers clock skew between us and the provider's window.
    """
    stated = getattr(exc, "retry_after", None)
    if isinstance(stated, int | float) and stated > 0:
        return min(float(stated) + 0.25, cap_seconds)
    match = _RETRY_AFTER_TEXT.search(str(exc))
    if match:
        seconds = float(match.group(1))
        if match.group(2).lower() == "ms":
            seconds /= 1000.0
        return min(seconds + 0.25, cap_seconds)
    return min(2.0**attempt, cap_seconds)


class LiteLLMClient:
    def __init__(
        self,
        *,
        ollama_base_url: str | None = None,
        max_retries: int | None = None,
        retry_cap_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = get_settings()
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries
        self.retry_cap_seconds = (
            settings.llm_retry_cap_seconds if retry_cap_seconds is None else retry_cap_seconds
        )
        self._sleep = sleep

    def _completion_with_retry(self, **kwargs: Any) -> Any:
        """Call the provider, waiting out throttling rather than failing the whole answer.

        Free hosted tiers are measured in tokens per minute, so a burst of questions will be
        throttled in normal use. Failing closed on a 429 would refuse an answer the data can
        perfectly well support, which is the wrong kind of refusal.
        """
        for attempt in range(1, self.max_retries + 2):
            try:
                return litellm.completion(**kwargs)
            except RETRYABLE as e:
                if attempt > self.max_retries:
                    raise
                self._sleep(retry_delay(e, attempt, self.retry_cap_seconds))
        raise AssertionError("unreachable")  # pragma: no cover

    def complete_json[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, str] | None = None,
    ) -> T:
        kwargs: dict[str, object] = {}
        if model.startswith("ollama/"):
            kwargs["api_base"] = self.ollama_base_url
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        with tracing.observation(
            (metadata or {}).get("node", "llm"),
            as_type="generation",
            model=model,
            input=messages,
            metadata=metadata,
            model_parameters={"temperature": temperature, "max_tokens": max_tokens},
        ) as gen:
            response = self._completion_with_retry(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            if gen is not None:
                usage = getattr(response, "usage", None)
                gen.update(
                    output=content,
                    usage_details={
                        "input": getattr(usage, "prompt_tokens", 0) or 0,
                        "output": getattr(usage, "completion_tokens", 0) or 0,
                    },
                )
        return parse_contract(content, schema)


Reply = str | dict[str, Any] | Callable[[str, str], str | dict[str, Any]]


class ScriptedLLM:
    """Returns scripted replies in order; each reply may be a dict, a JSON string, or a
    function of (system, user) so tests can assert on the prompt they received."""

    def __init__(self, replies: Iterable[Reply]) -> None:
        self._replies: deque[Reply] = deque(replies)
        self.calls: list[dict[str, str]] = []

    def complete_json[T: BaseModel](
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, str] | None = None,
    ) -> T:
        self.calls.append(
            {"model": model, "system": system, "user": user, "schema": schema.__name__}
        )
        if not self._replies:
            raise AssertionError(f"ScriptedLLM ran out of replies at call {len(self.calls)}")
        reply = self._replies.popleft()
        if callable(reply):
            reply = reply(system, user)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return parse_contract(content, schema)


def complete_json[T: BaseModel](
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    temperature: float = 0.0,
    max_tokens: int = 1024,
    metadata: dict[str, str] | None = None,
) -> T:
    """Module-level convenience wrapper around :class:`LiteLLMClient`."""
    return LiteLLMClient().complete_json(
        model=model,
        system=system,
        user=user,
        schema=schema,
        temperature=temperature,
        max_tokens=max_tokens,
        metadata=metadata,
    )
