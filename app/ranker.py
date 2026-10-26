"""Ask the model to rank a shortlist, and fall back to rating and votes when it cannot.

`recommend` is the path behind POST /api/recommendations: validate, filter, rank,
then join display fields from the catalog.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from app.catalog import Catalog
from app.config import settings
from app.filters import sort_by_popularity
from app.llm import LlmCallError, LlmLimitError, TokenBudget, complete_chat, parse_json_content
from app.prompt import build_messages
from app.schemas import (
    Preferences,
    RecommendationCard,
    RecommendationResponse,
    Restaurant,
)

FALLBACK_SUMMARY = (
    "This list is ordered by rating and popularity because a written recommendation was unavailable."
)


@dataclass(frozen=True)
class RankedItem:
    id: str
    rank: int
    explanation: str


@dataclass(frozen=True)
class Ranking:
    summary: str
    recommendations: list[RankedItem]
    explanation_source: str | None


def recommend(
    catalog: Catalog,
    payload: object,
    *,
    post: Callable[..., httpx.Response] | None = None,
    budget: TokenBudget | None = None,
) -> RecommendationResponse:
    """Validate, filter, rank, and join catalog facts.

    An empty shortlist returns guidance and does not call the model. Invalid
    preferences and unknown localities or cuisines are left for the route to
    turn into HTTP 400.
    """
    preferences = Preferences.model_validate(payload)
    shortlist = catalog.filter(preferences)
    if not shortlist.use_model:
        return RecommendationResponse(
            summary=shortlist.summary or "",
            explanation_source=None,
            filters_applied=shortlist.filters_applied,
            candidate_count=shortlist.candidate_count,
            recommendations=[],
        )

    ranking = rank_candidates(
        preferences,
        shortlist.candidates,
        post=post,
        budget=budget,
    )
    by_id = {item.id: item for item in ranking.recommendations}
    cards = [
        _card(restaurant, by_id[restaurant.id])
        for restaurant in catalog.get_many([item.id for item in ranking.recommendations])
        if restaurant.id in by_id
    ]
    source: Literal["llm", "fallback"] = "llm" if ranking.explanation_source == "llm" else "fallback"
    return RecommendationResponse(
        summary=ranking.summary,
        explanation_source=source,
        filters_applied=shortlist.filters_applied,
        candidate_count=shortlist.candidate_count,
        recommendations=cards,
    )


def _card(restaurant: Restaurant, item: RankedItem) -> RecommendationCard:
    """Copy the visible restaurant facts from the catalog row."""
    return RecommendationCard(
        rank=item.rank,
        id=restaurant.id,
        name=restaurant.name,
        cuisines=list(restaurant.cuisines),
        rating=restaurant.rating,
        votes=restaurant.votes,
        cost_for_two=restaurant.cost_for_two,
        address=restaurant.address,
        rest_type=list(restaurant.rest_type),
        online_order=restaurant.online_order,
        book_table=restaurant.book_table,
        explanation=item.explanation,
    )


def rank_candidates(
    preferences: Preferences,
    candidates: list[Restaurant],
    *,
    post: Callable[..., httpx.Response] | None = None,
    budget: TokenBudget | None = None,
) -> Ranking:
    """Rank the pre-ranked shortlist. An empty list does not call the model."""
    ordered = sort_by_popularity(candidates)[: settings.candidate_limit]
    if not ordered:
        return Ranking(summary="", recommendations=[], explanation_source=None)

    try:
        content = complete_chat(
            build_messages(preferences, ordered),
            budget=budget,
            post=post,
        )
    except (LlmCallError, LlmLimitError):
        return _fallback(preferences, ordered)

    parsed = parse_json_content(content)
    if parsed is None:
        return _fallback(preferences, ordered)
    accepted = _accept_model_picks(parsed, ordered, preferences.top_n)
    if accepted is None:
        return _fallback(preferences, ordered)
    return accepted


def fallback_explanation(restaurant: Restaurant) -> str:
    """A plain sentence from rating, votes, cuisine, and cost. Unrated rows omit a rating."""
    cuisines = ", ".join(restaurant.cuisines) if restaurant.cuisines else "an unspecified cuisine"
    if restaurant.cost_for_two is None:
        cost = "an unknown cost for two"
    else:
        cost = f"a cost for two of {restaurant.cost_for_two}"
    votes = f"{restaurant.votes} votes"
    if restaurant.rating is None:
        return f"Serves {cuisines} from {votes} with {cost}."
    return f"Rated {restaurant.rating:g} from {votes}. Serves {cuisines} with {cost}."


def _fallback(preferences: Preferences, ordered: list[Restaurant]) -> Ranking:
    chosen = ordered[: preferences.top_n]
    return Ranking(
        summary=FALLBACK_SUMMARY,
        explanation_source="fallback",
        recommendations=[
            RankedItem(
                id=restaurant.id,
                rank=position,
                explanation=_cap(fallback_explanation(restaurant)),
            )
            for position, restaurant in enumerate(chosen, start=1)
        ],
    )


@dataclass
class _Pick:
    index: int
    restaurant: Restaurant
    explanation: str
    rank: float | None


def _accept_model_picks(
    payload: dict[str, object],
    ordered: list[Restaurant],
    top_n: int,
) -> Ranking | None:
    raw = payload.get("recommendations")
    if not isinstance(raw, list):
        return None
    known = {restaurant.id: restaurant for restaurant in ordered}
    seen: set[str] = set()
    picks: list[_Pick] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        restaurant_id = entry.get("id")
        if not isinstance(restaurant_id, str) or restaurant_id not in known or restaurant_id in seen:
            continue
        seen.add(restaurant_id)
        explanation = entry.get("explanation")
        text = explanation.strip() if isinstance(explanation, str) else ""
        picks.append(
            _Pick(
                index=index,
                restaurant=known[restaurant_id],
                explanation=text or fallback_explanation(known[restaurant_id]),
                rank=_numeric_rank(entry.get("rank")),
            )
        )
    if not picks:
        return None
    picks.sort(key=lambda pick: (pick.rank is None, pick.rank if pick.rank is not None else 0, pick.index))
    summary = payload.get("summary")
    summary_text = summary.strip() if isinstance(summary, str) else ""
    return Ranking(
        summary=summary_text,
        explanation_source="llm",
        recommendations=[
            RankedItem(
                id=pick.restaurant.id,
                rank=position,
                explanation=_cap(pick.explanation),
            )
            for position, pick in enumerate(picks[:top_n], start=1)
        ],
    )


def _numeric_rank(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _cap(text: str) -> str:
    return text[: settings.explanation_length_cap]
