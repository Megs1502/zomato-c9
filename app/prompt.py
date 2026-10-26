"""One system message and one user message for a single ranking call."""

from __future__ import annotations

import json

from app.config import settings
from app.schemas import Preferences, Restaurant

DISH_LIKED_LIMIT = 8
DISH_CHAR_LIMIT = 80

SYSTEM_PROMPT = """You rank restaurants for one search and explain the picks.
Rank only ids from the user message, best fit first. Do not invent restaurants or fields.
Use additional_preferences as the tie-breaker. When that text does not separate two places, use rating and votes.
Explain each pick in two or three sentences using only the supplied fields.
Write summary as a short comparison of the restaurants you return.
Return JSON only, with at most top_n items, in this shape:
{"summary":"string","recommendations":[{"id":"string","rank":1,"explanation":"string"}]}
"""


def build_messages(
    preferences: Preferences,
    candidates: list[Restaurant],
) -> list[dict[str, str]]:
    """Preferences plus at most the candidate cap. Review text is included only when present."""
    payload = {
        "location": preferences.location,
        "budget": preferences.budget,
        "cuisine": preferences.cuisine,
        "min_rating": preferences.min_rating,
        "additional_preferences": preferences.additional_preferences,
        "top_n": preferences.top_n,
        "candidates": [
            _candidate_payload(restaurant)
            for restaurant in candidates[: settings.candidate_limit]
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _candidate_payload(restaurant: Restaurant) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": restaurant.id,
        "name": restaurant.name,
        "cuisines": list(restaurant.cuisines),
        "rating": restaurant.rating,
        "votes": restaurant.votes,
        "cost_for_two": restaurant.cost_for_two,
        "rest_type": list(restaurant.rest_type),
        "listed_types": list(restaurant.listed_types),
        "dish_liked": _capped_dishes(restaurant.dish_liked),
        "online_order": restaurant.online_order,
        "book_table": restaurant.book_table,
    }
    if restaurant.review_snippet:
        payload["review_snippet"] = restaurant.review_snippet
    return payload


def _capped_dishes(dishes: list[str]) -> list[str]:
    capped: list[str] = []
    for dish in dishes:
        text = dish.strip()
        if not text:
            continue
        capped.append(text[:DISH_CHAR_LIMIT])
        if len(capped) == DISH_LIKED_LIMIT:
            break
    return capped
