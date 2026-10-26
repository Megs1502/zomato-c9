"""Filter, budget, pre-rank, and relaxation. No network and no model call."""

import inspect

import pytest
from pydantic import ValidationError

from app.filters import (
    EMPTY_SUMMARY,
    PreferenceError,
    popularity_score,
    select_candidates,
    suggest,
)
from app.schemas import Preferences, Restaurant


def place(
    restaurant_id: str,
    *,
    location: str = "Banashankari",
    cuisines: tuple[str, ...] = ("Italian",),
    cost: int | None = 800,
    rating: float | None = 4.0,
    votes: int = 10,
) -> Restaurant:
    return Restaurant(
        id=restaurant_id,
        name=restaurant_id,
        location=location,
        cuisines=list(cuisines),
        cost_for_two=cost,
        rating=rating,
        votes=votes,
    )


def search(rows: list[Restaurant], **overrides: object) -> object:
    payload: dict[str, object] = {"location": "Banashankari", "budget": "medium"}
    payload.update(overrides)
    return select_candidates(rows, Preferences.model_validate(payload))


def test_structural_preferences_accept_defaults_and_bounds() -> None:
    parsed = Preferences.model_validate({"location": " Banashankari ", "budget": "Low"})
    assert parsed.location == "Banashankari"
    assert parsed.budget == "low"
    assert parsed.cuisine is None
    assert parsed.min_rating == 0
    assert parsed.additional_preferences == ""
    assert parsed.top_n == 5

    assert Preferences.model_validate(
        {"location": "Banashankari", "budget": "high", "additional_preferences": "a" * 300, "top_n": 1}
    ).top_n == 1
    assert Preferences.model_validate(
        {"location": "Banashankari", "budget": "high", "top_n": 8, "min_rating": 5}
    ).min_rating == 5
    assert Preferences.model_validate(
        {"location": "Banashankari", "budget": "medium", "cuisine": "  ", "additional_preferences": "   "}
    ).cuisine is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"budget": "low"},
        {"location": "   ", "budget": "low"},
        {"location": "Banashankari"},
        {"location": "Banashankari", "budget": "cheap"},
        {"location": "Banashankari", "budget": "low", "min_rating": -0.1},
        {"location": "Banashankari", "budget": "low", "min_rating": 5.1},
        {"location": "Banashankari", "budget": "low", "min_rating": "high"},
        {"location": "Banashankari", "budget": "low", "additional_preferences": "a" * 301},
        {"location": "Banashankari", "budget": "low", "top_n": 0},
        {"location": "Banashankari", "budget": "low", "top_n": 9},
        {"location": "Banashankari", "budget": "low", "top_n": -1},
        {"location": "Banashankari", "budget": "low", "top_n": 1.5},
        {"location": "Banashankari", "budget": "low", "top_n": "5"},
        {"location": "Banashankari", "budget": "low", "extra": "ignored", "top_n": True},
    ],
)
def test_invalid_preferences_fail_before_a_catalog_lookup(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Preferences.model_validate(payload)


def test_exact_locality_and_cuisine_hit_uses_catalog_spelling() -> None:
    rows = [
        place("jalsa", cuisines=("North Indian", "Italian"), rating=4.1, cost=800),
        place("second", cuisines=("Italian",), rating=4.2),
        place("third", cuisines=("Italian",), rating=4.5),
        place("other", location="Indiranagar", cuisines=("Italian",), rating=4.8),
    ]
    shortlist = search(rows, location=" banashankari ", cuisine="italian", min_rating=4.1)

    assert {restaurant.id for restaurant in shortlist.candidates} == {"jalsa", "second", "third"}
    applied = shortlist.filters_applied
    assert applied.location == "Banashankari"
    assert applied.cuisine == "Italian"
    assert applied.budget == ["medium"]
    assert applied.min_rating == 4.1
    assert applied.relaxed == []
    assert shortlist.candidate_count == 3
    assert shortlist.use_model is True
    assert shortlist.summary is None


def test_cuisine_match_is_a_whole_token() -> None:
    rows = [
        place("north", cuisines=("North Indian",)),
        place("india-1", cuisines=("India",)),
        place("india-2", cuisines=("India",)),
        place("india-3", cuisines=("India",)),
    ]
    shortlist = search(rows, cuisine="India")
    assert shortlist.filters_applied.cuisine == "India"
    assert shortlist.filters_applied.relaxed == []
    assert "north" not in {restaurant.id for restaurant in shortlist.candidates}

    with pytest.raises(PreferenceError) as exc_info:
        search([place("north", cuisines=("North Indian",))], cuisine="India")
    assert exc_info.value.field == "cuisine"
    assert len(exc_info.value.suggestions) <= 5


def test_unknown_locality_and_cuisine_carry_at_most_five_suggestions() -> None:
    rows = [place("jalsa", cuisines=("Italian", "Chinese"))]
    with pytest.raises(PreferenceError) as locality_error:
        search(rows, location="Delhi")
    assert locality_error.value.field == "location"
    assert locality_error.value.suggestions == []

    suggestions = suggest(
        "ItalianX",
        ["Italian", "Italian A", "Italian B", "Italian C", "Italian D", "Italian E"],
    )
    assert suggestions[0] == "Italian"
    assert len(suggestions) == 5

    with pytest.raises(PreferenceError) as cuisine_error:
        search(rows, cuisine="Itallian")
    assert cuisine_error.value.field == "cuisine"
    assert cuisine_error.value.suggestions == ["Italian"]


def test_missing_cost_is_excluded_and_budget_edges_follow_the_bands() -> None:
    missing = search(
        [place("missing", cost=None), place("a", cost=800), place("b", cost=900), place("c", cost=700)],
        budget="medium",
    )
    assert missing.filters_applied.relaxed == []
    assert "missing" not in {restaurant.id for restaurant in missing.candidates}

    low = search(
        [
            place("zero", cost=0),
            place("low-edge", cost=500),
            place("also-low", cost=250),
            place("medium-low", cost=501),
        ],
        budget="low",
    )
    assert low.filters_applied.relaxed == []
    assert {restaurant.id for restaurant in low.candidates} == {"zero", "low-edge", "also-low"}

    medium = search(
        [
            place("low-edge", cost=500),
            place("medium-low", cost=501),
            place("middle", cost=800),
            place("medium-high", cost=1000),
            place("high-edge", cost=1001),
        ],
        budget="medium",
    )
    assert medium.filters_applied.relaxed == []
    assert {restaurant.id for restaurant in medium.candidates} == {
        "medium-low",
        "middle",
        "medium-high",
    }

    high = search(
        [
            place("medium-high", cost=1000),
            place("high-edge", cost=1001),
            place("higher", cost=1400),
            place("highest", cost=2000),
        ],
        budget="high",
    )
    assert high.filters_applied.relaxed == []
    assert {restaurant.id for restaurant in high.candidates} == {"high-edge", "higher", "highest"}


def test_unrated_rows_stay_at_zero_and_drop_above_zero() -> None:
    rows = [
        place("rated", rating=4.0),
        place("same", rating=3.0),
        place("also", rating=3.5),
        place("missing", rating=None),
    ]
    kept = search(rows, min_rating=0)
    assert kept.filters_applied.relaxed == []
    assert {restaurant.id for restaurant in kept.candidates} == {"rated", "same", "also", "missing"}

    dropped = search(rows, min_rating=3)
    assert dropped.filters_applied.relaxed == []
    assert {restaurant.id for restaurant in dropped.candidates} == {"rated", "same", "also"}

    equal = search(
        [place("boundary", rating=4.0), place("b", rating=4.0), place("c", rating=4.0)],
        min_rating=4,
    )
    assert "boundary" in {restaurant.id for restaurant in equal.candidates}
    assert equal.filters_applied.relaxed == []


def test_score_orders_rated_rows_ahead_of_missing_ratings_and_breaks_ties_by_id() -> None:
    rows = [
        place("high", rating=5, votes=10),
        place("b-place", rating=4, votes=10),
        place("a-place", rating=4, votes=10),
        place("rated-zero", rating=1, votes=0),
        place("missing", rating=None, votes=500),
    ]
    shortlist = search(rows)
    assert [restaurant.id for restaurant in shortlist.candidates] == [
        "high",
        "a-place",
        "b-place",
        "rated-zero",
        "missing",
    ]
    assert popularity_score(rows[3]) == 0
    assert popularity_score(rows[4]) is None


def test_candidate_cap_is_fifteen_and_smaller_lists_keep_their_count() -> None:
    many = [place(f"r{votes:02d}", rating=4, votes=votes) for votes in range(1, 17)]
    capped = search(many)
    assert capped.candidate_count == 15
    assert len(capped.candidates) == 15
    assert capped.candidates[0].id == "r16"
    assert all(restaurant.votes > 1 for restaurant in capped.candidates)

    four = search([place(f"p{index}") for index in range(4)], top_n=5)
    assert four.candidate_count == 4
    assert len(four.candidates) == 4


def test_three_exact_matches_do_not_relax() -> None:
    rows = [place("a"), place("b"), place("c")]
    shortlist = search(rows, cuisine="Italian", min_rating=4)
    assert shortlist.filters_applied.relaxed == []
    assert shortlist.candidate_count == 3


def test_budget_widens_once_and_stops_before_cuisine_or_rating_changes() -> None:
    rows = [
        place("m1", cost=800),
        place("m2", cost=900),
        place("low", cost=400),
        place("high", cost=1500),
    ]
    shortlist = search(rows, budget="low", cuisine="Italian", min_rating=4)
    assert shortlist.filters_applied.relaxed == ["budget_widened"]
    assert shortlist.filters_applied.budget == ["low", "medium"]
    assert shortlist.filters_applied.cuisine == "Italian"
    assert shortlist.filters_applied.min_rating == 4
    assert {restaurant.id for restaurant in shortlist.candidates} == {"m1", "m2", "low"}


def test_high_budget_widens_to_medium_and_leaves_low_out() -> None:
    rows = [
        place("h1", cost=1500),
        place("h2", cost=1800),
        place("medium", cost=800),
        place("low", cost=300),
    ]
    shortlist = search(rows, budget="high")
    assert shortlist.filters_applied.relaxed == ["budget_widened"]
    assert shortlist.filters_applied.budget == ["high", "medium"]
    assert {restaurant.id for restaurant in shortlist.candidates} == {"h1", "h2", "medium"}


def test_medium_budget_widens_to_every_band() -> None:
    rows = [
        place("medium", cost=800),
        place("low", cost=300),
        place("high", cost=1500),
    ]
    shortlist = search(rows, budget="medium")
    assert shortlist.filters_applied.relaxed == ["budget_widened"]
    assert shortlist.filters_applied.budget == ["medium", "low", "high"]
    assert shortlist.candidate_count == 3


def test_dropping_cuisine_is_recorded_when_a_wider_budget_is_still_short() -> None:
    rows = [
        place("italian-1", cuisines=("Italian",)),
        place("italian-2", cuisines=("Italian",)),
        place("chinese", cuisines=("Chinese",)),
    ]
    shortlist = search(rows, cuisine="Italian", min_rating=4)
    assert shortlist.filters_applied.relaxed == ["budget_widened", "cuisine_dropped"]
    assert shortlist.filters_applied.cuisine is None
    assert shortlist.filters_applied.min_rating == 4
    assert shortlist.candidate_count == 3


def test_min_rating_lowers_by_half_points_until_three_match() -> None:
    rows = [
        place("high-1", rating=4.6),
        place("high-2", rating=4.2),
        place("mid", rating=3.6),
    ]
    shortlist = search(rows, cuisine="Italian", min_rating=4)
    assert shortlist.filters_applied.relaxed == [
        "budget_widened",
        "cuisine_dropped",
        "min_rating_lowered",
    ]
    assert shortlist.filters_applied.min_rating == 3.5
    assert shortlist.candidate_count == 3


def test_rating_already_at_zero_is_not_lowered() -> None:
    rows = [place("one", cuisines=("Italian",)), place("two", cuisines=("Chinese",))]
    shortlist = search(rows, cuisine="Italian", min_rating=0)
    assert shortlist.filters_applied.relaxed == ["budget_widened", "cuisine_dropped"]
    assert "min_rating_lowered" not in shortlist.filters_applied.relaxed
    assert shortlist.filters_applied.min_rating == 0
    assert shortlist.use_model is True
    assert shortlist.candidate_count == 2


def test_one_or_two_rows_after_relaxation_still_request_a_model() -> None:
    rows = [place("only", rating=4.8)]
    shortlist = search(rows, cuisine="Italian", min_rating=4)
    assert shortlist.candidate_count == 1
    assert shortlist.use_model is True
    assert shortlist.summary is None
    assert "min_rating_lowered" in shortlist.filters_applied.relaxed


def test_no_rows_after_relaxation_skip_the_model_and_ask_for_another_search() -> None:
    rows = [place("pricey", cost=1500)]
    shortlist = search(rows, budget="low", cuisine="Italian", min_rating=4)
    assert shortlist.candidates == []
    assert shortlist.candidate_count == 0
    assert shortlist.use_model is False
    assert shortlist.summary == EMPTY_SUMMARY
    assert "locality" in shortlist.summary
    assert "rating" in shortlist.summary


def test_a_locality_whose_rows_have_no_cost_mentions_the_unknown_cost() -> None:
    shortlist = search([place("blank", cost=None), place("also-blank", cost=None)], min_rating=4)
    assert shortlist.candidates == []
    assert shortlist.use_model is False
    assert shortlist.summary is not None
    assert "unknown cost" in shortlist.summary
    assert "rating" in shortlist.summary


def test_blank_cuisine_means_any_cuisine() -> None:
    rows = [place("italian", cuisines=("Italian",)), place("chinese", cuisines=("Chinese",)), place("thai", cuisines=("Thai",))]
    shortlist = search(rows, cuisine="   ")
    assert shortlist.filters_applied.cuisine is None
    assert shortlist.filters_applied.relaxed == []
    assert shortlist.candidate_count == 3


def test_an_open_cuisine_is_not_recorded_as_dropped() -> None:
    rows = [place("medium", cost=800), place("low", cost=400)]
    shortlist = search(rows, budget="medium", min_rating=0)
    assert shortlist.filters_applied.cuisine is None
    assert shortlist.filters_applied.relaxed == ["budget_widened"]
    assert {restaurant.id for restaurant in shortlist.candidates} == {"medium", "low"}


def test_empty_shortlist_does_not_reference_the_model_client() -> None:
    source = inspect.getsource(inspect.getmodule(select_candidates))
    assert "app.llm" not in source
    assert "chat/completions" not in source
    shortlist = search([place("only", cost=None)])
    assert shortlist.use_model is False
