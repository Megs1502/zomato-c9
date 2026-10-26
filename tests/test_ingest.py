"""Ingest edge cases. These tests never download the dataset."""

import ast
import json
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.ingest import (
    OUTPUT_COLUMNS,
    budget_band,
    build_meta,
    clean_records,
    cost_histogram,
    format_histogram,
    parse_cost,
    parse_rating,
    parse_yes_no,
    repair_text,
    review_snippet,
    split_tokens,
    write_outputs,
)

PHONE = "080 42297555"


def source_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "url": "https://example.test/jalsa",
        "address": "942, 21st Main Road, Banashankari, Bangalore",
        "name": "Jalsa",
        "online_order": "Yes",
        "book_table": "No",
        "rate": "4.1/5",
        "votes": 100,
        "phone": PHONE,
        "location": "Banashankari",
        "rest_type": "Casual Dining",
        "dish_liked": "Pasta, Pasta",
        "cuisines": "North Indian, Mughlai, Chinese",
        "approx_cost(for two people)": "800",
        "reviews_list": "[('Rated 4.0', 'RATED Great pasta')]",
        "menu_item": "[]",
        "listed_in(type)": "Buffet",
        "listed_in(city)": "Banashankari",
    }
    row.update(overrides)
    return row


def test_parse_rating_known_shapes() -> None:
    assert parse_rating("4.1/5") == 4.1
    assert parse_rating("4.1 /5") == 4.1
    assert parse_rating("NEW") is None
    assert parse_rating("-") is None
    assert parse_rating("") is None
    assert parse_rating(None) is None
    assert parse_rating("   ") is None
    assert parse_rating("6/5") is None
    assert parse_rating("-1/5") is None


def test_parse_cost_and_budget_edges() -> None:
    assert parse_cost("800") == 800
    assert parse_cost("1,200") == 1200
    assert parse_cost("") is None
    assert parse_cost(None) is None
    assert parse_cost("   ") is None
    assert parse_cost("500") == 500
    assert parse_cost("501") == 501
    assert parse_cost("1000") == 1000
    assert parse_cost("1001") == 1001
    assert parse_cost("0") == 0
    assert budget_band(500) == "low"
    assert budget_band(501) == "medium"
    assert budget_band(1000) == "medium"
    assert budget_band(1001) == "high"
    assert budget_band(0) == "low"
    assert budget_band(None) == "missing"
    assert budget_band(800) == "medium"
    assert budget_band(1200) == "high"


def test_yes_no_and_token_lists() -> None:
    assert parse_yes_no("Yes") is True
    assert parse_yes_no("no") is False
    assert parse_yes_no("YES") is True
    assert parse_yes_no("") is False
    assert parse_yes_no(None) is False
    assert split_tokens(None) == []
    assert split_tokens("North Indian, Mughlai, Chinese") == [
        "North Indian",
        "Mughlai",
        "Chinese",
    ]
    assert split_tokens(" North Indian, , North Indian, ") == ["North Indian"]


def test_review_snippets_are_short_and_optional() -> None:
    assert review_snippet(None) is None
    assert review_snippet("") is None
    assert review_snippet("[]") is None
    assert review_snippet("not a python literal") is None
    assert review_snippet("[('Rated 4.0', 'RATED Short and friendly')]") == "Short and friendly"

    long_text = "A" * 500
    snippet = review_snippet(
        str(
            [
                ("Rated 5.0", long_text),
                ("Rated 4.0", "Second visit"),
                ("Rated 3.0", "Third visit should be ignored"),
            ]
        )
    )
    assert snippet is not None
    first, second = snippet.split("\n\n")
    assert first == "A" * 280
    assert second == "Second visit"
    assert "Third" not in snippet

    kept = review_snippet("[('Rated 4.0', 'RATED Call 99999 00000 for a table')]")
    assert kept == "Call 99999 00000 for a table"


def test_encoding_repair_is_applied_only_when_it_is_safe() -> None:
    assert repair_text("CafÃ©") == "Café"
    assert repair_text("Foo Ã Bar") == "Foo Ã Bar"


def test_blank_name_is_dropped_and_chain_locations_stay_separate() -> None:
    rows = clean_records(
        [
            source_row(name="   "),
            source_row(name=None),
            source_row(name="Jalsa", address="1 First Road"),
            source_row(name="Jalsa", address="2 Second Road"),
        ]
    )
    assert [row["address"] for row in rows] == ["1 First Road", "2 Second Road"]


def test_duplicate_listings_merge_lists_and_keep_the_strongest_votes() -> None:
    rows = clean_records(
        [
            source_row(
                votes=10,
                rate="3.0/5",
                online_order="No",
                location="Banashankari",
                cuisines="Italian",
                **{
                    "listed_in(type)": "Buffet",
                    "listed_in(city)": "Banashankari",
                    "approx_cost(for two people)": "800",
                    "reviews_list": "[('Rated 3.0', 'RATED Quiet')]",
                },
            ),
            source_row(
                votes=50,
                rate="4.6/5",
                online_order="Yes",
                book_table="Yes",
                location="Basavanagudi",
                cuisines="italian, Chinese",
                **{
                    "listed_in(type)": "Cafes",
                    "listed_in(city)": "Jayanagar",
                    "approx_cost(for two people)": "600",
                    "reviews_list": "[]",
                },
            ),
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["votes"] == 50
    assert row["rating"] == 4.6
    assert row["online_order"] is True
    assert row["book_table"] is True
    assert row["location"] == "Basavanagudi"
    assert row["cost_for_two"] == 600
    assert row["cuisines"] == ["italian", "Chinese"]
    assert row["listed_types"] == ["Cafes", "Buffet"]
    assert row["areas"] == ["Jayanagar", "Banashankari"]
    assert row["review_snippet"] == "Quiet"
    assert row["dish_liked"] == ["Pasta"]


def test_vote_ties_prefer_the_higher_rating_then_the_earliest_row() -> None:
    higher_rating = clean_records(
        [
            source_row(votes=20, rate="3.5/5", location="Earlier"),
            source_row(votes=20, rate="4.2/5", location="Later"),
        ]
    )
    assert higher_rating[0]["location"] == "Later"
    assert higher_rating[0]["rating"] == 4.2

    earliest = clean_records(
        [
            source_row(votes=20, rate="4.0/5", location="First"),
            source_row(votes=20, rate="4.0/5", location="Second"),
        ]
    )
    assert earliest[0]["location"] == "First"


def test_missing_cost_on_the_chosen_row_can_be_filled_from_a_duplicate() -> None:
    rows = clean_records(
        [
            source_row(votes=5, **{"approx_cost(for two people)": "700"}),
            source_row(votes=9, **{"approx_cost(for two people)": None}),
        ]
    )
    assert rows[0]["votes"] == 9
    assert rows[0]["cost_for_two"] == 700


def test_address_spacing_and_case_share_one_id() -> None:
    rows = clean_records(
        [
            source_row(name="Jalsa", address="942,  21st   Main Road"),
            source_row(name="jalsa", address="942, 21st Main Road", votes=3),
        ]
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "jalsa|942, 21st main road"


def test_repaired_name_is_used_in_the_catalog() -> None:
    rows = clean_records([source_row(name="CafÃ© Down")])
    assert rows[0]["name"] == "Café Down"
    assert rows[0]["id"].startswith("café down|")


def test_blank_locality_stays_on_the_row_and_out_of_meta() -> None:
    rows = clean_records(
        [
            source_row(location="   ", cuisines="Chinese"),
            source_row(name="Other", address="9 Side Street", location="Indiranagar", cuisines="indian"),
        ]
    )
    meta = build_meta(rows)
    assert rows[0]["location"] == ""
    assert meta["localities"] == ["Indiranagar"]
    assert meta["cuisines"] == ["Chinese", "indian"]
    assert meta["restaurant_count"] == 2


def test_histogram_counts_missing_cost_separately() -> None:
    rows = clean_records(
        [
            source_row(name="Low", address="1", **{"approx_cost(for two people)": "500"}),
            source_row(name="Mid", address="2", **{"approx_cost(for two people)": "501"}),
            source_row(name="High", address="3", **{"approx_cost(for two people)": "1001"}),
            source_row(name="Unknown", address="4", **{"approx_cost(for two people)": None}),
        ]
    )
    counts = cost_histogram(rows)
    assert counts == {"low": 1, "medium": 1, "high": 1, "missing": 1}
    text = format_histogram(counts)
    assert "low: 1" in text
    assert "missing: 1" in text


def test_write_outputs_creates_files_and_drops_private_columns(tmp_path: Path) -> None:
    data_dir = tmp_path / "nested" / "data"
    rows = clean_records([source_row()])
    write_outputs(rows, data_dir)

    parquet_path = data_dir / "restaurants.parquet"
    meta_path = data_dir / "catalog_meta.json"
    assert parquet_path.is_file()
    assert meta_path.is_file()

    schema_names = set(pq.read_schema(parquet_path).names)
    assert schema_names == set(OUTPUT_COLUMNS)
    for forbidden in ("phone", "url", "menu_item", "reviews_list"):
        assert forbidden not in schema_names

    table = pq.read_table(parquet_path)
    stored = table.to_pylist()[0]
    assert stored["name"] == "Jalsa"
    assert stored["rating"] == 4.1
    assert stored["cost_for_two"] == 800
    assert PHONE not in json.dumps(stored)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["restaurant_count"] == 1
    assert meta["localities"] == ["Banashankari"]
    assert "North Indian" in meta["cuisines"]


def test_cleaning_the_same_rows_twice_is_identical() -> None:
    raw = [
        source_row(votes=1, **{"listed_in(type)": "Buffet"}),
        source_row(votes=4, rate="4.4/5", **{"listed_in(type)": "Delivery"}),
        source_row(name="Other", address="5 Hill Road"),
    ]
    assert clean_records(raw) == clean_records(list(raw))


def test_rows_without_rating_or_cost_are_kept() -> None:
    rows = clean_records(
        [
            source_row(
                rate="NEW",
                **{"approx_cost(for two people)": None},
            )
        ]
    )
    assert len(rows) == 1
    assert rows[0]["rating"] is None
    assert rows[0]["cost_for_two"] is None


def test_literal_review_payload_matches_the_dataset_shape() -> None:
    payload = ast.literal_eval("[('Rated 4.0', 'RATED\\n A beautiful place')]")
    assert review_snippet(str(payload)) == "A beautiful place"
