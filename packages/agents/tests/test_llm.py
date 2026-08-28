"""Throttling is normal traffic on a metered hosted tier, not a failure of the answer."""

from __future__ import annotations

from typing import Any

import litellm
import pytest
from pydantic import BaseModel

from askindia_agents.llm import ContractViolationError, LiteLLMClient, retry_delay


class Shape(BaseModel):
    ok: bool


def _rate_limited(message: str = "rate limited") -> litellm.RateLimitError:
    return litellm.RateLimitError(message=message, llm_provider="groq", model="m")


def _reply(content: str) -> Any:
    class _Msg:
        def __init__(self) -> None:
            self.content = content

    class _Choice:
        def __init__(self) -> None:
            self.message = _Msg()

    class _Response:
        def __init__(self) -> None:
            self.choices = [_Choice()]
            self.usage = None

    return _Response()


def _client(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]
) -> tuple[LiteLLMClient, list[float]]:
    """A client whose provider returns `outcomes` in order.

    An outcome that is an exception is raised; anything else is returned as the reply.
    """
    slept: list[float] = []
    calls = iter(outcomes)

    def fake_completion(**_: Any) -> Any:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LiteLLMClient(max_retries=3, retry_cap_seconds=5.0, sleep=slept.append)
    return client, slept


def test_retries_through_throttling_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client, slept = _client(monkeypatch, [_rate_limited(), _rate_limited(), _reply('{"ok": true}')])
    out = client.complete_json(model="groq/x", system="s", user="u", schema=Shape)
    assert out.ok is True
    assert len(slept) == 2, "one wait per throttled attempt"


def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    client, slept = _client(monkeypatch, [_rate_limited()] * 4)
    with pytest.raises(litellm.RateLimitError):
        client.complete_json(model="groq/x", system="s", user="u", schema=Shape)
    assert len(slept) == 3, "max_retries waits, then the error surfaces"


def test_contract_violation_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed reply is the model's answer, not a transient fault; retrying just burns quota."""
    client, slept = _client(monkeypatch, [_reply("not json")])
    with pytest.raises(ContractViolationError):
        client.complete_json(model="groq/x", system="s", user="u", schema=Shape)
    assert slept == []


def test_delay_prefers_the_wait_the_provider_states() -> None:
    groq = _rate_limited("Limit 8000, Used 7450. Please try again in 787.5ms.")
    assert retry_delay(groq, attempt=1, cap_seconds=30.0) == pytest.approx(1.0375)

    seconds = _rate_limited("Please try again in 12s.")
    assert retry_delay(seconds, attempt=1, cap_seconds=30.0) == pytest.approx(12.25)


def test_delay_backs_off_when_the_provider_says_nothing() -> None:
    silent = _rate_limited("too many requests")
    assert retry_delay(silent, attempt=1, cap_seconds=30.0) == 2.0
    assert retry_delay(silent, attempt=3, cap_seconds=30.0) == 8.0


def test_delay_never_exceeds_the_cap() -> None:
    assert retry_delay(_rate_limited("try again in 600s."), attempt=1, cap_seconds=30.0) == 30.0
    assert retry_delay(_rate_limited("nothing stated"), attempt=9, cap_seconds=30.0) == 30.0
