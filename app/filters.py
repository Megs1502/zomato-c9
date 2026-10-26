"""Hard filters, budget bands, pre-rank, and relaxation.

This module never calls a model. An empty shortlist tells the caller to skip that call.
"""

from __future__ import annotations

import difflib
import math
from collections.abc import Iterable

from app.config import ADJACENT_BUDGETS, BUDGET_BANDS, RELAXATION_ORDER, settings
from app.schemas import FiltersApplied, Preferences, Restaurant, Shortlist

SUGGESTION_LIMIT = 5
SUGGESTION_CUTOFF = 0.6

BUDGET_WIDENED, CUISINE_DROPPED, RATING_LOWERED = RELAXATION_ORDER

EMPTY_SUMMARY = "No restaurants match this search. Try another locality or a lower rating."
UNKNOWN_COST_SUMMARY = (
    "No restaurants match this search because places in {location} were skipped "
    "for an unknown cost. Try another locality or a lower rating."
)


class PreferenceError(ValueError):
    """A preference does not match the catalog. Phase 6 turns this into HTTP 400."""

    def __init__(self, field: str, message: str, suggestions: list[str]) -> None:
        self.field = field
        self.suggestions = suggestions
        super().__init__(message)


def select_candidates(
    restaurants: list[Restaurant],
    preferences: Preferences,
    *,
    localities: list[str] | None = None,
    cuisines: list[str] | None = None,
) -> Shortlist:
    """Resolve preferences, relax until three matches or the steps run out, then cap."""
    known_localities = localities if localities is not None else _labels(
        restaurant.location for restaurant in restaurants
    )
    known_cuisines = cuisines if cuisines is not None else _labels(
        cuisine for restaurant in restaurants for cuisine in restaurant.cuisines
    )
    location = resolve_label(preferences.location, known_localities, "location")
    cuisine = (
        None
        if preferences.cuisine is None
        else resolve_label(preferences.cuisine, known_cuisines, "cuisine")
    )
    return _relax(restaurants, preferences, location, cuisine)


def popularity_score(restaurant: Restaurant) -> float | None:
    """`rating * log(1 + votes)`. Missing ratings have no score and sort last."""
    if restaurant.rating is None:
        return None
    return restaurant.rating * math.log1p(max(restaurant.votes, 0))


def suggest(query: str, choices: list[str], *, limit: int = SUGGESTION_LIMIT) -> list[str]:
    """Up to `limit` close catalog spellings. Empty when nothing is close."""
    folded: dict[str, str] = {}
    for choice in choices:
        folded.setdefault(choice.casefold(), choice)
    matches = difflib.get_close_matches(
        query.strip().casefold(),
        list(folded),
        n=limit,
        cutoff=SUGGESTION_CUTOFF,
    )
    return [folded[match] for match in matches]


def resolve_label(value: str, choices: list[str], field: str) -> str:
    """Return the catalog spelling, or raise with at most five suggestions."""
    folded = value.casefold()
    for choice in choices:
        if choice.casefold() == folded:
            return choice
    raise PreferenceError(
        field,
        f"Unknown {field}.",
        suggest(value, choices),
    )


def _relax(
    restaurants: list[Restaurant],
    preferences: Preferences,
    location: str,
    cuisine: str | None,
) -> Shortlist:
    minimum = settings.min_matches_before_relax
    bands = [preferences.budget]
    rating = preferences.min_rating
    relaxed: list[str] = []

    found = _matching(restaurants, location, bands, cuisine, rating)
    if len(found) >= minimum:
        return _pack(restaurants, location, bands, cuisine, rating, relaxed, found)

    bands = _widened_bands(preferences.budget)
    relaxed.append(BUDGET_WIDENED)
    found = _matching(restaurants, location, bands, cuisine, rating)
    if len(found) >= minimum:
        return _pack(restaurants, location, bands, cuisine, rating, relaxed, found)

    if cuisine is not None:
        cuisine = None
        relaxed.append(CUISINE_DROPPED)
        found = _matching(restaurants, location, bands, cuisine, rating)
        if len(found) >= minimum:
            return _pack(restaurants, location, bands, cuisine, rating, relaxed, found)

    if rating > 0:
        relaxed.append(RATING_LOWERED)
        while len(found) < minimum and rating > 0:
            rating = max(0.0, round(rating - settings.rating_relax_step, 1))
            found = _matching(restaurants, location, bands, cuisine, rating)

    return _pack(restaurants, location, bands, cuisine, rating, relaxed, found)


def _pack(
    restaurants: list[Restaurant],
    location: str,
    bands: list[str],
    cuisine: str | None,
    rating: float,
    relaxed: list[str],
    found: list[Restaurant],
) -> Shortlist:
    ranked = sorted(found, key=_rank_key)[: settings.candidate_limit]
    summary = None if ranked else _empty_summary(restaurants, location)
    return Shortlist(
        candidates=ranked,
        filters_applied=FiltersApplied(
            location=location,
            budget=list(bands),
            cuisine=cuisine,
            min_rating=rating,
            relaxed=list(relaxed),
        ),
        candidate_count=len(ranked),
        summary=summary,
        use_model=bool(ranked),
    )


def _matching(
    restaurants: list[Restaurant],
    location: str,
    bands: list[str],
    cuisine: str | None,
    min_rating: float,
) -> list[Restaurant]:
    return [
        restaurant
        for restaurant in restaurants
        if _row_matches(restaurant, location, bands, cuisine, min_rating)
    ]


def _row_matches(
    restaurant: Restaurant,
    location: str,
    bands: list[str],
    cuisine: str | None,
    min_rating: float,
) -> bool:
    if restaurant.location.casefold() != location.casefold():
        return False
    if cuisine is not None and not any(
        token.casefold() == cuisine.casefold() for token in restaurant.cuisines
    ):
        return False
    if min_rating > 0 and (restaurant.rating is None or restaurant.rating < min_rating):
        return False
    return _cost_in_bands(restaurant.cost_for_two, bands)


def _cost_in_bands(cost: int | None, bands: list[str]) -> bool:
    if cost is None:
        return False
    return any(_cost_in_band(cost, band) for band in bands)


def _cost_in_band(cost: int, band: str) -> bool:
    lower, upper = BUDGET_BANDS[band]
    if upper is None:
        return cost >= lower
    return lower <= cost <= upper


def _widened_bands(budget: str) -> list[str]:
    bands = [budget]
    for band in ADJACENT_BUDGETS[budget]:
        if band not in bands:
            bands.append(band)
    return bands


def sort_by_popularity(restaurants: list[Restaurant]) -> list[Restaurant]:
    """Pre-rank order: higher score first, then more votes, then lower id."""
    return sorted(restaurants, key=_rank_key)


def _rank_key(restaurant: Restaurant) -> tuple[int, float, int, str]:
    score = popularity_score(restaurant)
    if score is None:
        return (1, 0.0, 0, restaurant.id)
    return (0, -score, -restaurant.votes, restaurant.id)


def _empty_summary(restaurants: list[Restaurant], location: str) -> str:
    at_location = [
        restaurant
        for restaurant in restaurants
        if restaurant.location.casefold() == location.casefold()
    ]
    if at_location and all(restaurant.cost_for_two is None for restaurant in at_location):
        return UNKNOWN_COST_SUMMARY.format(location=location)
    return EMPTY_SUMMARY


def _labels(values: Iterable[str]) -> list[str]:
    unique = {value for value in values if value}
    return sorted(unique, key=lambda value: (value.casefold(), value))
