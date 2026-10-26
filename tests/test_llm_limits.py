"""Groq request and token caps. These tests never call the network."""

import threading

import httpx
import pytest

from app.config import (
    GROQ_REQUESTS_PER_DAY,
    GROQ_REQUESTS_PER_MINUTE,
    GROQ_TOKENS_PER_DAY,
    GROQ_TOKENS_PER_MINUTE,
)
from app.llm import (
    LlmCallError,
    LlmLimitError,
    TokenBudget,
    chat_url,
    complete_chat,
    estimate_message_tokens,
)


class Response:
    def __init__(self, status_code: int, body: dict[str, object] | None = None, raw: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self._raw = raw

    def json(self) -> dict[str, object]:
        if self._body is None:
            raise ValueError(self._raw or "not json")
        return self._body


def budget_at(moment: list[float]) -> TokenBudget:
    return TokenBudget(clock=lambda: moment[0])


def test_prompt_estimate_is_rounded_up() -> None:
    messages = [{"role": "user", "content": "a"}]
    assert estimate_message_tokens(messages) == 17


def test_chat_url_keeps_a_single_slash() -> None:
    assert chat_url("https://api.groq.com/openai/v1/") == "https://api.groq.com/openai/v1/chat/completions"
    assert chat_url("https://api.groq.com/openai/v1") == "https://api.groq.com/openai/v1/chat/completions"


def test_reservation_uses_only_the_tokens_still_available() -> None:
    moment = [1_000.0]
    budget = budget_at(moment)
    first = budget.reserve(1_000)
    assert first.max_tokens == GROQ_TOKENS_PER_MINUTE - 1_000
    with pytest.raises(LlmLimitError):
        budget.reserve(1)

    budget.settle(first, 1_000)
    second = budget.reserve(500)
    assert second.max_tokens == GROQ_TOKENS_PER_MINUTE - 1_000 - 500


def test_a_new_minute_keeps_the_day_total() -> None:
    moment = [10_000.0]
    budget = budget_at(moment)
    budget.settle(budget.reserve(100), GROQ_TOKENS_PER_DAY - 900)
    moment[0] += 61
    allowance = budget.reserve(100)
    assert allowance.max_tokens == 800
    budget.settle(allowance, 900)
    moment[0] += 61
    with pytest.raises(LlmLimitError):
        budget.reserve(1)


def test_request_caps_stop_before_another_call() -> None:
    moment = [50_000.0]
    budget = budget_at(moment)
    for _ in range(GROQ_REQUESTS_PER_MINUTE):
        budget.settle(budget.reserve(1), 1)
    with pytest.raises(LlmLimitError):
        budget.reserve(1)

    for _ in range(GROQ_REQUESTS_PER_DAY - GROQ_REQUESTS_PER_MINUTE):
        moment[0] += 61
        budget.settle(budget.reserve(1), 1)
    moment[0] += 61
    with pytest.raises(LlmLimitError):
        budget.reserve(1)


def test_overlapping_reservations_cannot_share_the_same_minute() -> None:
    budget = TokenBudget(clock=lambda: 80_000.0)
    accepted: list[int] = []
    refused: list[str] = []
    gate = threading.Barrier(2)

    def attempt() -> None:
        gate.wait()
        try:
            accepted.append(budget.reserve(4_000).max_tokens)
        except LlmLimitError:
            refused.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert accepted == [GROQ_TOKENS_PER_MINUTE - 4_000]
    assert refused == ["refused"]


def test_complete_chat_sends_one_capped_request_and_records_actual_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr("app.llm.settings", settings.model_copy(update={"llm_api_key": "test-key"}))
    moment = [90_000.0]
    budget = budget_at(moment)
    seen: list[dict[str, object]] = []

    def post(payload: dict[str, object]) -> Response:
        seen.append(payload)
        return Response(200, {"choices": [{"message": {"content": "pong"}}], "usage": {"total_tokens": 120}})

    text = complete_chat(
        [{"role": "user", "content": "Reply with pong."}],
        budget=budget,
        post=post,
    )

    assert text == "pong"
    assert len(seen) == 1
    assert seen[0]["temperature"] == 0.2
    assert seen[0]["max_tokens"] == GROQ_TOKENS_PER_MINUTE - estimate_message_tokens(
        [{"role": "user", "content": "Reply with pong."}]
    )
    follow = budget.reserve(100)
    assert follow.max_tokens == GROQ_TOKENS_PER_MINUTE - 120 - 100


def test_blank_key_does_not_call_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    calls = {"count": 0}

    def post(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return Response(200, {"choices": [{"message": {"content": "no"}}]})

    monkeypatch.setattr("app.llm.settings", settings.model_copy(update={"llm_api_key": ""}))
    with pytest.raises(LlmCallError, match="LLM_API_KEY"):
        complete_chat([{"role": "user", "content": "hi"}], post=post)
    assert calls["count"] == 0


def test_provider_429_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    calls = {"count": 0}

    def post(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return Response(429, {"error": "rate limit"})

    monkeypatch.setattr("app.llm.settings", settings.model_copy(update={"llm_api_key": "test-key"}))
    with pytest.raises(LlmLimitError, match="429"):
        complete_chat(
            [{"role": "user", "content": "hi"}],
            budget=budget_at([100_000.0]),
            post=post,
        )
    assert calls["count"] == 1


def test_timeout_keeps_the_reservation_so_the_next_call_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    calls = {"count": 0}

    def time_out(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.llm.settings", settings.model_copy(update={"llm_api_key": "test-key"}))
    budget = budget_at([200_000.0])
    with pytest.raises(LlmCallError, match="timed out"):
        complete_chat([{"role": "user", "content": "hi"}], budget=budget, post=time_out)
    with pytest.raises(LlmLimitError):
        complete_chat([{"role": "user", "content": "x"}], budget=budget, post=time_out)
    assert calls["count"] == 1


def test_a_prompt_larger_than_the_minute_budget_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr("app.llm.settings", settings.model_copy(update={"llm_api_key": "test-key"}))
    calls = {"count": 0}

    def post(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return Response(200, {"choices": [{"message": {"content": "no"}}], "usage": {"total_tokens": 1}})

    huge = "a" * (GROQ_TOKENS_PER_MINUTE * 3)
    with pytest.raises(LlmLimitError, match="token budget"):
        complete_chat([{"role": "user", "content": huge}], budget=budget_at([300_000.0]), post=post)
    assert calls["count"] == 0
