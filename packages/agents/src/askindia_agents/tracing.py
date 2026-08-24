"""Langfuse tracing (SDK v4, OpenTelemetry-based). Every node and model call becomes an
observation under one trace per question. Silently disabled when no keys are configured."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator
from typing import Any

_ENABLED: bool | None = None


def _keys() -> tuple[str, str, str] | None:
    """Langfuse credentials from the environment, falling back to the .env-backed settings."""
    public, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST")
    if not (public and secret):
        try:
            from askindia_agents.settings import get_settings

            s = get_settings()
        except Exception:
            return None
        if not (s.langfuse_public_key and s.langfuse_secret_key):
            return None
        public = s.langfuse_public_key.get_secret_value()
        secret = s.langfuse_secret_key.get_secret_value()
        host = host or s.langfuse_base_url
    return public, secret, host or "https://cloud.langfuse.com"


def enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = _keys() is not None
    return _ENABLED


_CONFIGURED = False


def _client() -> Any:
    from langfuse import get_client

    configure()
    keys = _keys()
    assert keys is not None
    return get_client(public_key=keys[0])


def configure() -> None:
    """Instantiate the client once with explicit credentials (env may hold only the .env values)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    keys = _keys()
    if keys is None:
        return
    from langfuse import Langfuse

    Langfuse(public_key=keys[0], secret_key=keys[1], base_url=keys[2])
    _CONFIGURED = True


@contextlib.contextmanager
def observation(
    name: str, *, as_type: str = "span", input: Any = None, metadata: Any = None, **kwargs: Any
) -> Iterator[Any]:
    """Context manager yielding the Langfuse observation (or None when tracing is off)."""
    if not enabled():
        yield None
        return
    with _client().start_as_current_observation(
        name=name, as_type=as_type, input=input, metadata=metadata, **kwargs
    ) as obs:
        yield obs


def traced_node(name: str, fn: Callable[..., Any], *, as_type: str = "chain") -> Callable[..., Any]:
    def wrapped(state: Any) -> Any:
        with observation(name, as_type=as_type, input=_state_preview(state)) as obs:
            out = fn(state)
            if obs is not None:
                obs.update(output=_state_preview(out))
            return out

    wrapped.__name__ = fn.__name__
    return wrapped


def flush() -> None:
    if enabled():
        _client().flush()


def _state_preview(state: Any, limit: int = 2000) -> Any:
    if not isinstance(state, dict):
        return state
    out: dict[str, Any] = {}
    for k, v in state.items():
        text = repr(v)
        out[k] = v if len(text) <= limit else text[:limit] + "..."
    return out
