"""In-memory restaurant catalog loaded once at startup."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pyarrow.parquet as pq

from app.filters import select_candidates
from app.schemas import Preferences, Restaurant, Shortlist

INGEST_INSTRUCTION = (
    "Cleaned catalog not found at data/restaurants.parquet. "
    "Run the ingest script before starting the API: python -m pipeline.ingest"
)


class Catalog:
    """Restaurants, localities, and cuisines kept in memory after startup."""

    def __init__(
        self,
        restaurants: list[Restaurant],
        *,
        written_meta: dict[str, object] | None = None,
    ) -> None:
        self._by_id: dict[str, Restaurant] = {}
        for restaurant in restaurants:
            self._by_id.setdefault(restaurant.id, restaurant)
        self._restaurants = list(self._by_id.values())
        self._localities = _sorted_labels(
            restaurant.location for restaurant in self._restaurants if restaurant.location
        )
        self._cuisines = _sorted_labels(
            cuisine
            for restaurant in self._restaurants
            for cuisine in restaurant.cuisines
            if cuisine
        )
        # Kept so startup reads the ingest sidecar, but lists always come from parquet.
        self.written_meta = written_meta

    def restaurant_count(self) -> int:
        """Restaurants held in memory after startup."""
        return len(self._restaurants)

    def list_localities(self) -> list[str]:
        return list(self._localities)

    def list_cuisines(self) -> list[str]:
        return list(self._cuisines)

    def get_many(self, ids: list[str]) -> list[Restaurant]:
        """Return known restaurants in the caller's order, once each."""
        found: list[Restaurant] = []
        seen: set[str] = set()
        for restaurant_id in ids:
            if restaurant_id in seen:
                continue
            seen.add(restaurant_id)
            restaurant = self._by_id.get(restaurant_id)
            if restaurant is not None:
                found.append(restaurant)
        return found

    def filter(self, preferences: Preferences | dict[str, object]) -> Shortlist:
        """Apply hard filters, relaxation, and the candidate cap. Does not call a model."""
        parsed = (
            preferences
            if isinstance(preferences, Preferences)
            else Preferences.model_validate(preferences)
        )
        return select_candidates(
            self._restaurants,
            parsed,
            localities=self.list_localities(),
            cuisines=self.list_cuisines(),
        )


def load_catalog(path: Path) -> Catalog:
    """Read the parquet catalog once. Locality and cuisine lists come from its rows."""
    if not path.is_file():
        raise RuntimeError(f"{INGEST_INSTRUCTION} Looked for: {path}")
    try:
        table = pq.read_table(path)
        restaurants = [
            Restaurant.model_validate(_normalize_row(row)) for row in table.to_pylist()
        ]
    except Exception as exc:
        raise RuntimeError(
            f"{INGEST_INSTRUCTION} Looked for: {path}. The file could not be read as a catalog."
        ) from exc
    return Catalog(restaurants, written_meta=_read_written_meta(path.parent / "catalog_meta.json"))


def _normalize_row(row: dict[str, object]) -> dict[str, object]:
    votes = row["votes"]
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"] or "",
        "location": row["location"] or "",
        "areas": list(row["areas"] or []),
        "cuisines": list(row["cuisines"] or []),
        "cost_for_two": row["cost_for_two"],
        "rating": row["rating"],
        "votes": 0 if votes is None else votes,
        "rest_type": list(row["rest_type"] or []),
        "online_order": bool(row["online_order"]),
        "book_table": bool(row["book_table"]),
        "dish_liked": list(row["dish_liked"] or []),
        "listed_types": list(row["listed_types"] or []),
        "review_snippet": row["review_snippet"],
    }


def _read_written_meta(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _sorted_labels(values: Iterable[str]) -> list[str]:
    unique = {value for value in values if isinstance(value, str) and value}
    return sorted(unique, key=lambda value: (value.casefold(), value))
