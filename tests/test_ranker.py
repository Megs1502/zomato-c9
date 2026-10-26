"""Prompt, model JSON, fallback, and POST /api/recommendations.

The HTTP client is fake. These tests do not call Groq and do not need an API key.
"""

import json
import threading
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.catalog import load_catalog
from app.config import load_settings, settings
from app.llm import TokenBudget, parse_json_content
from app.main import app, get_ranker_budget, get_ranker_post
from app.prompt import DISH_LIKED_LIMIT, SYSTEM_PROMPT, build_messages
from app.ranker import FALLBACK_SUMMARY, rank_candidates, recommend
from app.schemas import Preferences, RecommendationResponse, Restaurant
from pipeline.ingest import write_outputs


class Response:
    def __init__(self, status_code: int, body: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, object]:
        if self._body is None:
            raise ValueError("not json")
        return self._body


def preferences(**overrides: object) -> Preferences:
    payload: dict[str, object] = {
        "location": "Banashankari",
        "budget": "medium",
        "cuisine": "Italian",
        "min_rating": 4,
        "top_n": 5,
    }
    payload.update(overrides)
    return Preferences.model_validate(payload)


def place(
    restaurant_id: str,
    *,
    rating: float | None = 4.1,
    votes: int = 10,
    cost: int | None = 800,
    cuisines: tuple[str, ...] = ("Italian",),
    dishes: tuple[str, ...] = (),
    snippet: str | None = None,
) -> Restaurant:
    return Restaurant(
        id=restaurant_id,
        name=restaurant_id,
        location="Banashankari",
        cuisines=list(cuisines),
        cost_for_two=cost,
        rating=rating,
        votes=votes,
        rest_type=["Casual Dining"],
        online_order=True,
        book_table=False,
        dish_liked=list(dishes),
        listed_types=["Delivery"],
        review_snippet=snippet,
    )


def fresh_budget() -> TokenBudget:
    return TokenBudget(clock=lambda: 5_000_000.0)


def chat(content: str, status: int = 200) -> Response:
    return Response(
        status,
        {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 40}},
    )


def model_payload(recommendations: list[dict[str, object]], summary: str | None = "A short comparison.") -> str:
    body: dict[str, object] = {"recommendations": recommendations}
    if summary is not None:
        body["summary"] = summary
    return json.dumps(body)


def test_prompt_caps_candidates_and_dishes_and_omits_private_fields() -> None:
    rows = []
    for votes in range(16, 0, -1):
        rows.append(
            place(
                f"r{votes:02d}",
                votes=votes,
                dishes=tuple(f"Dish-{index}" for index in range(12)),
                snippet="Quiet room" if votes == 2 else None,
            )
        )
    messages = build_messages(preferences(), rows)

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "tie-breaker" in messages[0]["content"]
    assert "JSON only" in SYSTEM_PROMPT
    user = json.loads(messages[1]["content"])
    assert len(user["candidates"]) == 15
    assert [candidate["id"] for candidate in user["candidates"]][0] == "r16"
    assert all(candidate["id"] != "r01" for candidate in user["candidates"])
    assert user["candidates"][0]["dish_liked"] == [f"Dish-{index}" for index in range(DISH_LIKED_LIMIT)]
    without_snippet = next(candidate for candidate in user["candidates"] if candidate["id"] == "r03")
    with_snippet = next(candidate for candidate in user["candidates"] if candidate["id"] == "r02")
    assert "review_snippet" not in without_snippet
    assert with_snippet["review_snippet"] == "Quiet room"
    allowed = {
        "id",
        "name",
        "cuisines",
        "rating",
        "votes",
        "cost_for_two",
        "rest_type",
        "listed_types",
        "dish_liked",
        "online_order",
        "book_table",
        "review_snippet",
    }
    assert set(with_snippet) <= allowed
    serialized = messages[1]["content"]
    assert "phone" not in serialized
    assert "menu_item" not in serialized
    assert '"url"' not in serialized


def test_prompt_includes_the_free_text_preference() -> None:
    messages = build_messages(
        preferences(additional_preferences="quick service"),
        [place("jalsa")],
    )
    assert "quick service" in messages[1]["content"]
    assert "tie-breaker" in messages[0]["content"]


def test_json_fence_is_stripped_and_other_shapes_are_rejected() -> None:
    raw = model_payload([{"id": "jalsa", "rank": 1, "explanation": "Fits."}])
    assert parse_json_content(raw) is not None
    assert parse_json_content(f"```json\n{raw}\n```") is not None
    assert parse_json_content(f"Here you go:\n{raw}") is None
    assert parse_json_content(f"[{raw}]") is None
    assert parse_json_content('{"summary":') is None


def test_valid_json_keeps_model_order_by_rank_and_drops_unknown_ids() -> None:
    rows = [place("known"), place("other", votes=50, rating=4.8)]
    content = model_payload(
        [
            {"id": "missing", "rank": 1, "explanation": "Invented."},
            {"id": "known", "rank": 2, "explanation": "Known and specific."},
            {"id": "known", "rank": 1, "explanation": "Duplicate."},
        ],
        summary="One real place.",
    )
    ranking = rank_candidates(
        preferences(),
        rows,
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "llm"
    assert ranking.summary == "One real place."
    assert [item.id for item in ranking.recommendations] == ["known"]
    assert ranking.recommendations[0].explanation == "Known and specific."
    assert ranking.recommendations[0].rank == 1


def test_fenced_json_is_accepted() -> None:
    content = "```json\n" + model_payload(
        [{"id": "jalsa", "rank": 1, "explanation": "Inside the fence."}]
    ) + "\n```"
    ranking = rank_candidates(
        preferences(),
        [place("jalsa")],
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "llm"
    assert ranking.recommendations[0].explanation == "Inside the fence."


def test_rank_order_limits_and_missing_summary() -> None:
    rows = [place("a"), place("b"), place("c"), place("d")]
    content = json.dumps(
        {
            "recommendations": [
                {"id": "a", "rank": 5, "explanation": "Fifth."},
                {"id": "b", "explanation": "No rank."},
                {"id": "c", "rank": 1, "explanation": "First."},
                {"id": "d", "rank": 2, "explanation": "Second."},
                {"id": "a", "rank": 0, "explanation": "Later copy."},
            ]
        }
    )
    ranking = rank_candidates(
        preferences(top_n=2),
        rows,
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "llm"
    assert ranking.summary == ""
    assert [item.id for item in ranking.recommendations] == ["c", "d"]
    assert [item.rank for item in ranking.recommendations] == [1, 2]


def test_fewer_model_picks_are_not_filled_from_the_fallback() -> None:
    content = model_payload([{"id": "only", "rank": 4, "explanation": "Just this one."}])
    ranking = rank_candidates(
        preferences(top_n=5),
        [place("only"), place("other", votes=1)],
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "llm"
    assert [item.id for item in ranking.recommendations] == ["only"]


def test_empty_explanation_uses_the_plain_sentence_and_long_text_is_cut() -> None:
    long_text = "A" * (settings.explanation_length_cap + 50)
    content = model_payload(
        [
            {"id": "blank", "rank": 1, "explanation": "  "},
            {"id": "long", "rank": 2, "explanation": long_text},
        ]
    )
    ranking = rank_candidates(
        preferences(),
        [place("blank", rating=4.2, votes=15, cost=900), place("long", votes=3)],
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "llm"
    blank = ranking.recommendations[0]
    assert blank.id == "blank"
    assert "Rated 4.2" in blank.explanation
    assert "15 votes" in blank.explanation
    assert "900" in blank.explanation
    assert "Italian" in blank.explanation
    assert len(ranking.recommendations[1].explanation) == settings.explanation_length_cap


def test_a_mismatched_number_in_the_explanation_is_left_as_written() -> None:
    content = model_payload(
        [{"id": "jalsa", "rank": 1, "explanation": "Rated 9.9 and costs 1, which is not the catalog."}]
    )
    ranking = rank_candidates(
        preferences(),
        [place("jalsa", rating=4.1, cost=800)],
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.recommendations[0].explanation.startswith("Rated 9.9")


@pytest.mark.parametrize(
    "content",
    [
        "I would pick a place, but this is not JSON.",
        "[]",
        '{"summary": "cut"',
        model_payload([]),
        model_payload([{"id": "nope", "rank": 1, "explanation": "Unknown."}, {"id": "nope", "rank": 2, "explanation": "Again."}]),
    ],
)
def test_unusable_model_text_falls_back(content: str) -> None:
    rows = [place("b-place", rating=4, votes=10), place("a-place", rating=4, votes=10), place("high", rating=5, votes=100)]
    ranking = rank_candidates(
        preferences(),
        list(reversed(rows)),
        post=lambda _payload: chat(content),
        budget=fresh_budget(),
    )
    assert ranking.explanation_source == "fallback"
    assert [item.id for item in ranking.recommendations] == ["high", "a-place", "b-place"]
    assert ranking.summary == FALLBACK_SUMMARY


def test_timeout_non_json_and_http_errors_fall_back_without_a_second_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings as live_settings

    calls = {"count": 0}
    rows = [place("later", rating=3, votes=1), place("sooner", rating=5, votes=4)]

    def time_out(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        raise httpx.TimeoutException("timed out")

    ranking = rank_candidates(preferences(), rows, post=time_out, budget=fresh_budget())
    assert calls["count"] == 1
    assert ranking.explanation_source == "fallback"
    assert [item.id for item in ranking.recommendations] == ["sooner", "later"]

    def not_json(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return Response(200, None)

    ranking = rank_candidates(preferences(), rows, post=not_json, budget=fresh_budget())
    assert ranking.explanation_source == "fallback"
    assert calls["count"] == 2

    def rejected(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return Response(500, {"error": "down"})

    ranking = rank_candidates(preferences(), rows, post=rejected, budget=fresh_budget())
    assert ranking.explanation_source == "fallback"
    assert calls["count"] == 3

    monkeypatch.setattr("app.llm.settings", live_settings.model_copy(update={"llm_api_key": ""}))

    def unused(_payload: dict[str, object]) -> Response:
        calls["count"] += 1
        return chat("{}")

    ranking = rank_candidates(preferences(), rows, post=unused, budget=fresh_budget())
    assert calls["count"] == 3
    assert ranking.explanation_source == "fallback"


def test_fallback_sentence_omits_a_missing_rating_and_repeats_exactly() -> None:
    rows = [
        place("unrated", rating=None, votes=12, cost=500, cuisines=("South Indian",)),
        place("rated", rating=4.6, votes=20, cost=700),
    ]

    def fail(_payload: dict[str, object]) -> Response:
        raise httpx.ConnectError("offline")

    first = rank_candidates(preferences(min_rating=0), rows, post=fail, budget=fresh_budget())
    second = rank_candidates(preferences(min_rating=0), list(reversed(rows)), post=fail, budget=fresh_budget())
    assert [item.id for item in first.recommendations] == [item.id for item in second.recommendations]
    assert [item.id for item in first.recommendations] == ["rated", "unrated"]
    unrated = next(item for item in first.recommendations if item.id == "unrated")
    assert "Rated" not in unrated.explanation
    assert "12 votes" in unrated.explanation
    assert "500" in unrated.explanation
    assert "South Indian" in unrated.explanation
    rated = next(item for item in first.recommendations if item.id == "rated")
    assert "Rated 4.6" in rated.explanation
    assert "20 votes" in rated.explanation
    assert "700" in rated.explanation
    assert "rating and popularity" in first.summary
    assert "written recommendation was unavailable" in first.summary


def test_empty_shortlist_does_not_call_the_model() -> None:
    def post(_payload: dict[str, object]) -> Response:
        raise AssertionError("the model was called")

    ranking = rank_candidates(preferences(), [], post=post, budget=fresh_budget())
    assert ranking.recommendations == []
    assert ranking.explanation_source is None


def test_fallback_respects_top_n() -> None:
    rows = [place(f"p{index}", rating=4, votes=index) for index in range(1, 5)]
    ranking = rank_candidates(
        preferences(top_n=2),
        rows,
        post=lambda _payload: chat("not json"),
        budget=fresh_budget(),
    )
    assert [item.id for item in ranking.recommendations] == ["p4", "p3"]
    assert len(ranking.recommendations) == 2


def catalog_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "place-0|0 road",
        "name": "Place 0",
        "address": "0 Road",
        "location": "Banashankari",
        "areas": ["Banashankari"],
        "cuisines": ["Italian"],
        "cost_for_two": 800,
        "rating": 4.0,
        "votes": 100,
        "rest_type": ["Casual Dining"],
        "online_order": False,
        "book_table": False,
        "dish_liked": ["Pasta"],
        "listed_types": ["Buffet"],
        "review_snippet": "Quiet room",
    }
    row.update(overrides)
    return row


def italian_rows(count: int) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        rows.append(
            catalog_row(
                id=f"place-{index}|{index} road",
                name=f"Place {index}",
                address=f"{index} Road",
                rating=4.5 if index == 0 else 4.0,
                votes=100 - index,
                online_order=index == 0,
                book_table=index == 1,
            )
        )
    return rows


def write_catalog(directory: Path, rows: list[dict[str, object]]) -> Path:
    write_outputs(rows, directory)
    return directory / "restaurants.parquet"


def search_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "location": "Banashankari",
        "budget": "medium",
        "cuisine": "Italian",
        "min_rating": 0,
        "top_n": 5,
    }
    body.update(overrides)
    return body


@pytest.fixture
def recommendation_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A client whose catalog and model call stay inside the test."""
    holder: dict[str, TestClient] = {}

    def open_client(
        rows: list[dict[str, object]],
        post: object,
        *,
        when: float = 9_000_000.0,
    ) -> TestClient:
        path = write_catalog(tmp_path, rows)
        configured = load_settings(env_file=None).model_copy(
            update={"llm_api_key": "test-key", "catalog_path": path}
        )
        monkeypatch.setattr("app.main.settings", configured)
        monkeypatch.setattr("app.llm.settings", configured)
        budget = TokenBudget(clock=lambda: when)
        app.dependency_overrides[get_ranker_post] = lambda: post
        app.dependency_overrides[get_ranker_budget] = lambda: budget
        client = TestClient(app)
        client.__enter__()
        holder["client"] = client
        return client

    yield open_client
    app.dependency_overrides.clear()
    client = holder.get("client")
    if client is not None:
        client.__exit__(None, None, None)


def test_recommendations_join_catalog_facts_in_model_order(recommendation_api) -> None:
    rows = italian_rows(3)
    calls = {"n": 0}

    def post(_payload: dict[str, object]) -> Response:
        calls["n"] += 1
        return chat(
            model_payload(
                [
                    {"id": rows[2]["id"], "rank": 1, "explanation": "Rated 9.9 and costs 1."},
                    {"id": rows[0]["id"], "rank": 2, "explanation": "A solid second."},
                    {"id": "not-a-candidate", "rank": 3, "explanation": "Drop this id."},
                ],
                summary="Place 2 fits the request.",
            )
        )

    client = recommendation_api(rows, post)
    response = client.post(
        "/api/recommendations",
        json={**search_body(min_rating=4), "note": "ignored", "phone": "999"},
    )

    assert response.status_code == 200
    body = response.json()
    assert calls["n"] == 1
    assert body["explanation_source"] == "llm"
    assert body["summary"] == "Place 2 fits the request."
    assert body["candidate_count"] == 3
    assert body["filters_applied"]["location"] == "Banashankari"
    assert body["filters_applied"]["budget"] == ["medium"]
    assert body["filters_applied"]["cuisine"] == "Italian"
    assert body["filters_applied"]["min_rating"] == 4
    assert body["filters_applied"]["relaxed"] == []
    cards = body["recommendations"]
    assert [card["id"] for card in cards] == [rows[2]["id"], rows[0]["id"]]
    assert [card["rank"] for card in cards] == [1, 2]
    assert {card["id"] for card in cards} <= {row["id"] for row in rows}
    first = cards[0]
    assert first["name"] == "Place 2"
    assert first["cuisines"] == ["Italian"]
    assert first["rating"] == 4.0
    assert first["votes"] == 98
    assert first["cost_for_two"] == 800
    assert first["address"] == "2 Road"
    assert first["rest_type"] == ["Casual Dining"]
    assert first["online_order"] is False
    assert first["book_table"] is False
    assert "9.9" in first["explanation"]
    assert first["rating"] != 9.9
    assert first["cost_for_two"] != 1


def test_unknown_locality_and_cuisine_return_400(recommendation_api) -> None:
    def post(_payload: dict[str, object]) -> Response:
        raise AssertionError("the model was called")

    client = recommendation_api(italian_rows(3), post)

    delhi = client.post("/api/recommendations", json={"location": "Delhi", "budget": "medium"})
    assert delhi.status_code == 400
    delhi_body = delhi.json()
    assert delhi_body["field"] == "location"
    assert isinstance(delhi_body["suggestions"], list)
    assert len(delhi_body["suggestions"]) <= 5

    typo = client.post("/api/recommendations", json={"location": "Banashankri", "budget": "medium"})
    assert typo.status_code == 400
    assert typo.json()["suggestions"] == ["Banashankari"]
    assert len(typo.json()["suggestions"]) <= 5

    cuisine = client.post(
        "/api/recommendations",
        json={"location": "Banashankari", "budget": "medium", "cuisine": "Martian"},
    )
    assert cuisine.status_code == 400
    cuisine_body = cuisine.json()
    assert cuisine_body["field"] == "cuisine"
    assert len(cuisine_body["suggestions"]) <= 5


def test_invalid_payloads_return_400(recommendation_api) -> None:
    def post(_payload: dict[str, object]) -> Response:
        raise AssertionError("the model was called")

    client = recommendation_api(italian_rows(1), post)
    headers = {"content-type": "application/json"}

    assert client.post("/api/recommendations", content=b"", headers=headers).status_code == 400
    assert client.post("/api/recommendations", content=b"not-json", headers=headers).status_code == 400
    assert client.post("/api/recommendations", json=[]).status_code == 400

    top_n = client.post("/api/recommendations", json=search_body(top_n="5"))
    assert top_n.status_code == 400
    assert top_n.json()["field"] == "top_n"
    assert top_n.json()["suggestions"] == []

    missing = client.post("/api/recommendations", json={"budget": "medium"})
    assert missing.status_code == 400
    assert missing.json()["field"] == "location"


def test_empty_shortlist_returns_guidance_without_calling_the_model(recommendation_api) -> None:
    calls = {"n": 0}

    def post(_payload: dict[str, object]) -> Response:
        calls["n"] += 1
        return chat("{}")

    client = recommendation_api(
        [catalog_row(id="none|1 road", name="No Cost", address="1 Road", cost_for_two=None)],
        post,
    )
    response = client.post("/api/recommendations", json=search_body())

    assert response.status_code == 200
    body = response.json()
    assert calls["n"] == 0
    assert body["recommendations"] == []
    assert body["candidate_count"] == 0
    assert "explanation_source" not in body
    assert body["summary"] == (
        "No restaurants match this search because places in Banashankari were skipped "
        "for an unknown cost. Try another locality or a lower rating."
    )


def test_provider_error_returns_fallback_cards(recommendation_api) -> None:
    def post(_payload: dict[str, object]) -> Response:
        raise httpx.TimeoutException("timed out")

    rows = italian_rows(3)
    client = recommendation_api(rows, post)
    response = client.post("/api/recommendations", json=search_body())

    assert response.status_code == 200
    body = response.json()
    assert body["explanation_source"] == "fallback"
    assert body["summary"] == FALLBACK_SUMMARY
    assert body["candidate_count"] == 3
    assert [card["id"] for card in body["recommendations"]] == [row["id"] for row in rows]
    first = body["recommendations"][0]
    assert first["rating"] == 4.5
    assert first["cost_for_two"] == 800
    assert "4.5" in first["explanation"]
    assert "800" in first["explanation"]


def test_candidate_count_is_the_capped_shortlist_before_top_n(recommendation_api) -> None:
    rows = italian_rows(15)

    def post(_payload: dict[str, object]) -> Response:
        picks: list[dict[str, object]] = [{"id": "missing", "rank": 1, "explanation": "no"}]
        for index, row in enumerate(rows):
            picks.append(
                {
                    "id": row["id"],
                    "rank": 2 if index == len(rows) - 1 else index + 3,
                    "explanation": "Listed.",
                }
            )
        return chat(model_payload(picks))

    client = recommendation_api(rows, post)
    response = client.post("/api/recommendations", json=search_body(top_n=1))

    assert response.status_code == 200
    body = response.json()
    assert body["candidate_count"] == 15
    assert body["candidate_count"] <= 15
    cards = body["recommendations"]
    assert len(cards) == 1
    assert cards[0]["id"] == rows[-1]["id"]
    assert cards[0]["rank"] == 1
    assert cards[0]["rating"] == 4.0
    assert cards[0]["cost_for_two"] == 800
    assert {card["id"] for card in cards} <= {row["id"] for row in rows}


def test_overlapping_searches_read_the_same_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "app.llm.settings",
        load_settings(env_file=None).model_copy(update={"llm_api_key": "test-key"}),
    )
    path = write_catalog(tmp_path, italian_rows(3))
    catalog = load_catalog(path)
    barrier = threading.Barrier(2)

    def post(_payload: dict[str, object]) -> Response:
        barrier.wait(timeout=3)
        return chat(
            model_payload([{"id": "place-2|2 road", "rank": 1, "explanation": "Later."}])
        )

    results: list[RecommendationResponse] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(
                recommend(
                    catalog,
                    search_body(),
                    post=post,
                    budget=TokenBudget(clock=lambda: 8_000_000.0),
                )
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert len(results) == 2
    for result in results:
        assert result.recommendations[0].id == "place-2|2 road"
        assert result.recommendations[0].name == "Place 2"
        assert result.recommendations[0].cost_for_two == 800


def test_repeated_searches_do_not_reload_the_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = italian_rows(3)
    path = write_catalog(tmp_path, rows)
    configured = load_settings(env_file=None).model_copy(
        update={"llm_api_key": "test-key", "catalog_path": path}
    )
    monkeypatch.setattr("app.main.settings", configured)
    monkeypatch.setattr("app.llm.settings", configured)
    reads = {"n": 0}
    real_read = pq.read_table

    def counting(source: object, *args: object, **kwargs: object) -> object:
        reads["n"] += 1
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr("app.catalog.pq.read_table", counting)
    budget = TokenBudget(clock=lambda: 7_000_000.0)
    app.dependency_overrides[get_ranker_post] = lambda: (
        lambda _payload: chat(
            model_payload([{"id": rows[0]["id"], "rank": 1, "explanation": "First."}])
        )
    )
    app.dependency_overrides[get_ranker_budget] = lambda: budget
    try:
        with TestClient(app) as client:
            assert reads["n"] == 1
            first = client.post("/api/recommendations", json=search_body())
            second = client.post("/api/recommendations", json=search_body())
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["explanation_source"] == "llm"
        assert second.json()["explanation_source"] == "llm"
        assert reads["n"] == 1
    finally:
        app.dependency_overrides.clear()
