"""Catalog load and GET /api/meta. These tests do not call a model."""

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.catalog import load_catalog
from app.config import load_settings
from app.main import app
from pipeline.ingest import write_outputs


def restaurant_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "jalsa|1 first road",
        "name": "Jalsa",
        "address": "1 First Road",
        "location": "Banashankari",
        "areas": ["Banashankari"],
        "cuisines": ["North Indian", "Italian"],
        "cost_for_two": 800,
        "rating": 4.1,
        "votes": 100,
        "rest_type": ["Casual Dining"],
        "online_order": True,
        "book_table": False,
        "dish_liked": ["Pasta"],
        "listed_types": ["Buffet"],
        "review_snippet": "Great pasta",
    }
    row.update(overrides)
    return row


def write_catalog(directory: Path, rows: list[dict[str, object]]) -> Path:
    write_outputs(rows, directory)
    return directory / "restaurants.parquet"


def test_get_many_skips_unknown_ids_and_keeps_caller_order(tmp_path: Path) -> None:
    path = write_catalog(
        tmp_path,
        [
            restaurant_row(id="b|road", name="Beta", address="B Road", location="Indiranagar"),
            restaurant_row(id="a|road", name="Alpha", address="A Road", location="Banashankari"),
        ],
    )
    catalog = load_catalog(path)

    found = catalog.get_many(["b|road", "missing", "a|road", "b|road"])

    assert [restaurant.id for restaurant in found] == ["b|road", "a|road"]
    assert found[0].name == "Beta"
    assert found[0].cost_for_two == 800
    assert found[0].rating == 4.1


def test_localities_come_from_parquet_when_meta_is_stale(tmp_path: Path) -> None:
    path = write_catalog(tmp_path, [restaurant_row()])
    stale = {
        "restaurant_count": 0,
        "localities": ["Only In Stale Meta"],
        "cuisines": ["Only In Stale Meta"],
    }
    (tmp_path / "catalog_meta.json").write_text(json.dumps(stale), encoding="utf-8")

    catalog = load_catalog(path)

    assert catalog.list_localities() == ["Banashankari"]
    assert catalog.list_cuisines() == ["Italian", "North Indian"]
    assert catalog.written_meta == stale


def test_empty_parquet_starts_with_empty_lists(tmp_path: Path) -> None:
    path = write_catalog(tmp_path, [])
    catalog = load_catalog(path)

    assert catalog.list_localities() == []
    assert catalog.list_cuisines() == []
    assert catalog.get_many(["anything"]) == []


def test_catalog_filter_uses_the_loaded_rows(tmp_path: Path) -> None:
    catalog = load_catalog(
        write_catalog(
            tmp_path,
            [
                restaurant_row(),
                restaurant_row(id="beta|2 road", name="Beta", address="2 Road"),
                restaurant_row(id="gamma|3 road", name="Gamma", address="3 Road"),
            ],
        )
    )
    shortlist = catalog.filter(
        {"location": " banashankari ", "budget": "medium", "cuisine": "italian"}
    )
    assert "jalsa|1 first road" in {restaurant.id for restaurant in shortlist.candidates}
    assert shortlist.filters_applied.location == "Banashankari"
    assert shortlist.filters_applied.cuisine == "Italian"
    assert shortlist.filters_applied.relaxed == []
    assert shortlist.use_model is True


def test_meta_reads_the_real_catalog_once(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = {"count": 0}
    original = pq.read_table

    def counting(path: object, *args: object, **kwargs: object) -> object:
        reads["count"] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr("app.catalog.pq.read_table", counting)

    with TestClient(app) as client:
        first = client.get("/api/meta")
        second = client.get("/api/meta")
        health = client.get("/api/health")

    assert reads["count"] == 1
    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body == second.json()
    assert "Banashankari" in body["localities"]
    assert body["cuisines"]
    assert body["budgets"] == ["low", "medium", "high"]
    assert body["default_min_rating"] == 0
    assert "Only In Stale Meta" not in body["localities"]
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["restaurants"] > 0


def test_meta_serves_a_fixture_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write_catalog(
        tmp_path,
        [
            restaurant_row(location="Indiranagar", cuisines=["Chinese"]),
            restaurant_row(
                id="cafe|2 road",
                name="Cafe",
                address="2 Road",
                location="Banashankari",
                cuisines=["Italian"],
            ),
        ],
    )
    monkeypatch.setattr(
        "app.main.settings",
        load_settings(env_file=None).model_copy(update={"catalog_path": path}),
    )

    with TestClient(app) as client:
        response = client.get("/api/meta")
        health = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "restaurants": 2}
    assert body["localities"] == ["Banashankari", "Indiranagar"]
    assert body["cuisines"] == ["Chinese", "Italian"]
    assert body["budgets"] == ["low", "medium", "high"]
    assert body["default_min_rating"] == 0
