"""Load the Zomato dataset, clean it, and write the catalog.

The request path never calls this module. Run it before starting the API:

    python -m pipeline.ingest
"""

from __future__ import annotations

import ast
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.config import BUDGET_BANDS, settings

DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"
SNIPPET_LIMIT = 280
MAX_SNIPPETS = 2

COST_COLUMN = "approx_cost(for two people)"
LISTED_TYPE_COLUMN = "listed_in(type)"
LISTED_CITY_COLUMN = "listed_in(city)"

OUTPUT_COLUMNS = (
    "id",
    "name",
    "address",
    "location",
    "areas",
    "cuisines",
    "cost_for_two",
    "rating",
    "votes",
    "rest_type",
    "online_order",
    "book_table",
    "dish_liked",
    "listed_types",
    "review_snippet",
)

CATALOG_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("name", pa.string()),
        ("address", pa.string()),
        ("location", pa.string()),
        ("areas", pa.list_(pa.string())),
        ("cuisines", pa.list_(pa.string())),
        ("cost_for_two", pa.int64()),
        ("rating", pa.float64()),
        ("votes", pa.int64()),
        ("rest_type", pa.list_(pa.string())),
        ("online_order", pa.bool_()),
        ("book_table", pa.bool_()),
        ("dish_liked", pa.list_(pa.string())),
        ("listed_types", pa.list_(pa.string())),
        ("review_snippet", pa.string()),
    ]
)

_RATING_WITH_SCALE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*5", re.IGNORECASE)
_RATING_BARE = re.compile(r"(\d+(?:\.\d+)?)")
_MOJIBAKE_MARKERS = ("Ã", "Â")


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if type(value).__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _unwrap(value: object) -> object:
    """Turn numpy or pandas scalars into plain Python values."""
    if is_missing(value) or isinstance(value, (str, bytes, list, tuple, dict)):
        return value
    item = getattr(value, "item", None)
    if not callable(item):
        return value
    try:
        plain = item()
    except (ValueError, TypeError):
        return value
    return value if plain is value else plain


def normalize_spaces(value: str) -> str:
    return " ".join(value.split())


def repair_text(value: str) -> str:
    """Undo UTF-8 text that was decoded as Latin-1 or cp1252, when that is safe."""
    current = value
    for _ in range(4):
        if not any(marker in current for marker in _MOJIBAKE_MARKERS):
            return current
        repaired = _decode_mojibake(current)
        if repaired is None or repaired == current:
            return current
        if _marker_count(repaired) < _marker_count(current):
            current = repaired
            continue
        return current
    return current


def _marker_count(value: str) -> int:
    return sum(value.count(marker) for marker in _MOJIBAKE_MARKERS)


def _decode_mojibake(value: str) -> str | None:
    for encoding in ("latin-1", "cp1252"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired and "\ufffd" not in repaired:
            return repaired
    return None


def parse_rating(value: object) -> float | None:
    value = _unwrap(value)
    if is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if 0 <= number <= 5 else None

    text = str(value).strip()
    if text.casefold() in {"new", "-", "nan"}:
        return None
    match = _RATING_WITH_SCALE.fullmatch(text) or _RATING_BARE.fullmatch(text)
    if match is None:
        return None
    number = float(match.group(1))
    return number if 0 <= number <= 5 else None


def parse_cost(value: object) -> int | None:
    value = _unwrap(value)
    if is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text.isdigit():
        return None
    return int(text)


def parse_votes(value: object) -> int:
    value = _unwrap(value)
    if is_missing(value) or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            return 0
        return int(value)
    text = str(value).strip().replace(",", "")
    if text.isdigit():
        return int(text)
    return 0


def parse_yes_no(value: object) -> bool:
    value = _unwrap(value)
    if is_missing(value):
        return False
    return str(value).strip().casefold() == "yes"


def split_tokens(value: object) -> list[str]:
    value = _unwrap(value)
    if is_missing(value):
        return []
    seen: dict[str, str] = {}
    for part in str(value).split(","):
        token = normalize_spaces(repair_text(part))
        if not token:
            continue
        key = token.casefold()
        if key not in seen:
            seen[key] = token
    return list(seen.values())


def clean_label(value: object) -> str:
    value = _unwrap(value)
    if is_missing(value):
        return ""
    return normalize_spaces(repair_text(str(value)))


def restaurant_id(name: str, address: str) -> str:
    return f"{name.casefold()}|{address.casefold()}"


def review_snippet(value: object) -> str | None:
    excerpts: list[str] = []
    for item in _parse_reviews(value):
        excerpt = _excerpt_text(item)
        if excerpt is None:
            continue
        excerpts.append(excerpt[:SNIPPET_LIMIT])
        if len(excerpts) == MAX_SNIPPETS:
            break
    if not excerpts:
        return None
    return "\n\n".join(excerpts)


def _parse_reviews(value: object) -> list[object]:
    value = _unwrap(value)
    if is_missing(value):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    text = str(value).strip()
    if text in {"", "[]"}:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return []
    if isinstance(parsed, (list, tuple)):
        return list(parsed)
    return []


def _excerpt_text(item: object) -> str | None:
    raw = ""
    if isinstance(item, (list, tuple)):
        if len(item) >= 2 and isinstance(item[1], str):
            raw = item[1]
        elif len(item) >= 1 and isinstance(item[0], str):
            raw = item[0]
    elif isinstance(item, str):
        raw = item
    text = normalize_spaces(repair_text(raw))
    if text.casefold().startswith("rated "):
        text = text[6:].strip()
    elif text.casefold() == "rated":
        text = ""
    return text or None


def budget_band(cost: int | None) -> str:
    if cost is None:
        return "missing"
    for name, (lower, upper) in BUDGET_BANDS.items():
        if upper is None and cost >= lower:
            return name
        if upper is not None and lower <= cost <= upper:
            return name
    return "missing"


def cost_histogram(records: list[dict[str, object]]) -> dict[str, int]:
    counts = {"low": 0, "medium": 0, "high": 0, "missing": 0}
    for record in records:
        cost = record.get("cost_for_two")
        band = budget_band(cost if isinstance(cost, int) else None)
        counts[band] = counts.get(band, 0) + 1
    return counts


def format_histogram(counts: dict[str, int]) -> str:
    lines = ["Cost histogram (cost for two):"]
    for band in ("low", "medium", "high", "missing"):
        lines.append(f"  {band}: {counts.get(band, 0)}")
    return "\n".join(lines)


def prepare_record(record: dict[str, object], order: int) -> dict[str, object] | None:
    name = clean_label(record.get("name"))
    if not name:
        return None
    address = clean_label(record.get("address"))
    return {
        "order": order,
        "id": restaurant_id(name, address),
        "name": name,
        "address": address,
        "location": clean_label(record.get("location")),
        "areas": split_tokens(record.get(LISTED_CITY_COLUMN)),
        "cuisines": split_tokens(record.get("cuisines")),
        "cost_for_two": parse_cost(record.get(COST_COLUMN)),
        "rating": parse_rating(record.get("rate")),
        "votes": parse_votes(record.get("votes")),
        "rest_type": split_tokens(record.get("rest_type")),
        "online_order": parse_yes_no(record.get("online_order")),
        "book_table": parse_yes_no(record.get("book_table")),
        "dish_liked": split_tokens(record.get("dish_liked")),
        "listed_types": split_tokens(record.get(LISTED_TYPE_COLUMN)),
        "review_snippet": review_snippet(record.get("reviews_list")),
    }


def clean_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for order, record in enumerate(records):
        prepared = prepare_record(record, order)
        if prepared is not None:
            grouped[str(prepared["id"])].append(prepared)
    merged = [merge_group(rows) for _, rows in sorted(grouped.items())]
    return merged


def merge_group(rows: list[dict[str, object]]) -> dict[str, object]:
    chosen = max(rows, key=_choice_key)
    ordered = sorted(rows, key=lambda row: int(row["order"]))
    merged = {
        "id": chosen["id"],
        "name": chosen["name"],
        "address": chosen["address"],
        "location": chosen["location"],
        "areas": _union_tokens(chosen, ordered, "areas"),
        "cuisines": _union_tokens(chosen, ordered, "cuisines"),
        "cost_for_two": _prefer_scalar(chosen, ordered, "cost_for_two"),
        "rating": chosen["rating"],
        "votes": chosen["votes"],
        "rest_type": _union_tokens(chosen, ordered, "rest_type"),
        "online_order": chosen["online_order"],
        "book_table": chosen["book_table"],
        "dish_liked": _union_tokens(chosen, ordered, "dish_liked"),
        "listed_types": _union_tokens(chosen, ordered, "listed_types"),
        "review_snippet": _prefer_scalar(chosen, ordered, "review_snippet"),
    }
    return merged


def _choice_key(row: dict[str, object]) -> tuple[int, float, int]:
    votes = int(row["votes"])
    rating = row["rating"]
    rating_score = float(rating) if isinstance(rating, (int, float)) else -1.0
    return (votes, rating_score, -int(row["order"]))


def _union_tokens(
    chosen: dict[str, object],
    ordered: list[dict[str, object]],
    field: str,
) -> list[str]:
    seen: dict[str, str] = {}
    for row in (chosen, *ordered):
        values = row[field]
        if not isinstance(values, list):
            continue
        for token in values:
            if not isinstance(token, str) or not token:
                continue
            key = token.casefold()
            if key not in seen:
                seen[key] = token
    return list(seen.values())


def _prefer_scalar(
    chosen: dict[str, object],
    ordered: list[dict[str, object]],
    field: str,
) -> object:
    if chosen[field] is not None:
        return chosen[field]
    for row in ordered:
        if row[field] is not None:
            return row[field]
    return None


def build_meta(records: list[dict[str, object]]) -> dict[str, object]:
    localities = sorted(
        {str(row["location"]) for row in records if row.get("location")},
        key=lambda value: (value.casefold(), value),
    )
    cuisines = sorted(
        {
            token
            for row in records
            for token in row.get("cuisines", [])
            if isinstance(token, str) and token
        },
        key=lambda value: (value.casefold(), value),
    )
    return {
        "restaurant_count": len(records),
        "localities": localities,
        "cuisines": cuisines,
    }


def write_outputs(records: list[dict[str, object]], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    rows = [{column: record.get(column) for column in OUTPUT_COLUMNS} for record in records]
    table = pa.Table.from_pylist(rows, schema=CATALOG_SCHEMA)
    pq.write_table(table, data_dir / "restaurants.parquet")
    meta_path = data_dir / "catalog_meta.json"
    meta_path.write_text(
        json.dumps(build_meta(records), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_source_records() -> list[dict[str, object]]:
    from datasets import load_dataset

    dataset = load_dataset(DATASET_ID)
    split_name = "train" if "train" in dataset else next(iter(dataset))
    frame = dataset[split_name].to_pandas()
    return frame.to_dict(orient="records")


def main() -> None:
    records = clean_records(load_source_records())
    data_dir = settings.project_root / "data"
    write_outputs(records, data_dir)
    print(format_histogram(cost_histogram(records)))
    print(f"Wrote {len(records)} restaurants to {data_dir / 'restaurants.parquet'}")


if __name__ == "__main__":
    main()
