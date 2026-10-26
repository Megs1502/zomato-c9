"""One Groq chat completion, kept inside the published request and token caps.

The process keeps rolling one-minute and one-day windows. A call reserves its
worst case (prompt estimate plus max_tokens) before the request is sent, then
replaces that reservation with the provider's actual usage. Nothing in this
module retries.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.config import (
    GROQ_REQUESTS_PER_DAY,
    GROQ_REQUESTS_PER_MINUTE,
    GROQ_TOKENS_PER_DAY,
    GROQ_TOKENS_PER_MINUTE,
    settings,
)

TEMPERATURE = 0.2
MINUTE_SECONDS = 60
DAY_SECONDS = 24 * 60 * 60
# Characters per token is often about 4. Dividing by 3 overestimates so a call
# is refused early instead of spending past the minute cap.
CHARS_PER_TOKEN = 3
MESSAGE_OVERHEAD_TOKENS = 16


class LlmLimitError(RuntimeError):
    """The call would exceed a Groq cap, or Groq returned 429. Do not retry."""


class LlmCallError(RuntimeError):
    """The provider failed or the key is missing. Do not retry inside the client."""


@dataclass
class _Usage:
    at: float
    tokens: int


@dataclass(frozen=True)
class Reservation:
    """Worst-case hold placed before a request leaves the process."""

    max_tokens: int
    _usage: _Usage


class TokenBudget:
    """Shared windows for requests and tokens. Safe for overlapping calls."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = time.time if clock is None else clock
        self._lock = threading.Lock()
        self._events: list[_Usage] = []

    def reserve(self, prompt_tokens: int) -> Reservation:
        """Hold prompt + completion tokens, or refuse before any request is sent."""
        if prompt_tokens < 1:
            raise LlmLimitError("The prompt is empty, so no model call was sent.")
        with self._lock:
            now = self._clock()
            self._drop_expired(now)
            minute = [event for event in self._events if event.at > now - MINUTE_SECONDS]
            if len(minute) >= GROQ_REQUESTS_PER_MINUTE or len(self._events) >= GROQ_REQUESTS_PER_DAY:
                raise LlmLimitError("The model request budget is exhausted.")
            remaining = min(
                GROQ_TOKENS_PER_MINUTE - sum(event.tokens for event in minute),
                GROQ_TOKENS_PER_DAY - sum(event.tokens for event in self._events),
            )
            max_tokens = remaining - prompt_tokens
            if max_tokens < 1:
                raise LlmLimitError("The model token budget is exhausted.")
            usage = _Usage(at=now, tokens=prompt_tokens + max_tokens)
            self._events.append(usage)
            return Reservation(max_tokens=max_tokens, _usage=usage)

    def settle(self, reservation: Reservation, tokens: int) -> None:
        """Replace the worst-case hold with the tokens the provider actually used."""
        with self._lock:
            reservation._usage.tokens = max(0, tokens)

    def _drop_expired(self, now: float) -> None:
        cutoff = now - DAY_SECONDS
        self._events = [event for event in self._events if event.at > cutoff]


model_budget = TokenBudget()


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    """High estimate of prompt tokens, including a small per-message overhead."""
    total = 0
    for message in messages:
        content = message.get("content") or ""
        total += math.ceil(len(content) / CHARS_PER_TOKEN) + MESSAGE_OVERHEAD_TOKENS
    return max(total, 1)


def chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


_FENCE = re.compile(r"^```(?:json)?\s*(.*)\s*```$", re.DOTALL | re.IGNORECASE)


def parse_json_content(text: str) -> dict[str, object] | None:
    """Parse a JSON object, unwrapping one markdown fence. Anything else is unusable."""
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced is not None:
        body = fenced.group(1).strip()
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def complete_chat(
    messages: list[dict[str, str]],
    *,
    budget: TokenBudget | None = None,
    post: Callable[..., httpx.Response] | None = None,
) -> str:
    """Send one completion. Raises before the network when the local budget cannot fit it."""
    if not settings.llm_api_key:
        raise LlmCallError("LLM_API_KEY is empty, so no model call was sent.")

    active = model_budget if budget is None else budget
    prompt_tokens = estimate_message_tokens(messages)
    reservation = active.reserve(prompt_tokens)
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": reservation.max_tokens,
    }
    try:
        response = _send(payload, post)
    except httpx.TimeoutException as exc:
        raise LlmCallError("The model request timed out.") from exc
    except httpx.HTTPError as exc:
        raise LlmCallError("The model request failed.") from exc

    if response.status_code == 429:
        active.settle(reservation, 0)
        raise LlmLimitError("The model provider rejected the call with status 429.")
    if response.status_code >= 400:
        raise LlmCallError(f"The model provider rejected the call with status {response.status_code}.")

    try:
        body = response.json()
    except ValueError as exc:
        raise LlmCallError("The model returned a response that is not JSON.") from exc
    if not isinstance(body, dict):
        raise LlmCallError("The model returned a response that is not JSON.")

    active.settle(reservation, _total_tokens(body, reservation._usage.tokens))
    return _message_text(body)


def _send(payload: dict[str, object], post: Callable[..., httpx.Response] | None) -> httpx.Response:
    if post is not None:
        return post(payload)
    return httpx.post(
        chat_url(settings.llm_base_url),
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )


def _total_tokens(body: dict[str, object], fallback: int) -> int:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return fallback
    total = usage.get("total_tokens")
    if isinstance(total, bool) or not isinstance(total, int):
        return fallback
    return max(0, total)


def _message_text(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LlmCallError("The model returned no message.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LlmCallError("The model returned no message.")
    content = message.get("content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise LlmCallError("The model returned no text.")
    return content
