"""Thin LiteLLM wrapper: one call, strict JSON out, validated into a Pydantic model."""

from __future__ import annotations

import json

import litellm
from pydantic import BaseModel, ValidationError

from askindia_agents.settings import get_settings

litellm.suppress_debug_info = True


class ContractViolationError(ValueError):
    """The model did not return the requested JSON shape."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


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
    """Call ``model`` and parse its reply as ``schema``. Raises :class:`ContractViolationError`."""
    settings = get_settings()
    kwargs: dict[str, object] = {}
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_base_url
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
    try:
        payload = json.loads(_strip_fences(content))
    except json.JSONDecodeError as e:
        raise ContractViolationError(f"model reply is not JSON: {content[:200]!r}") from e
    try:
        return schema.model_validate(payload)
    except ValidationError as e:
        raise ContractViolationError(f"model reply violates {schema.__name__}: {e}") from e
