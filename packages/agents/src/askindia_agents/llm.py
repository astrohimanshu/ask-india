"""LLM access: one JSON-contract call, validated into a Pydantic model.

`LiteLLMClient` is the real backend (Ollama in development, Azure OpenAI in production — the
model id in settings decides). `ScriptedLLM` replays canned replies so every graph node can be
unit-tested without a model.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol

import litellm
from pydantic import BaseModel, ValidationError

from askindia_agents.settings import get_settings

litellm.suppress_debug_info = True


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


class LiteLLMClient:
    def __init__(self, *, ollama_base_url: str | None = None) -> None:
        self.ollama_base_url = ollama_base_url or get_settings().ollama_base_url

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
        response = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            metadata=metadata or {},
            **kwargs,
        )
        content = response.choices[0].message.content or ""
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
