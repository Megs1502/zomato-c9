"""FastAPI application. The catalog is loaded once when the process starts."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.catalog import INGEST_INSTRUCTION, Catalog, load_catalog
from app.config import DEFAULT_MIN_RATING, settings
from app.filters import PreferenceError
from app.llm import TokenBudget
from app.ranker import recommend
from app.schemas import CatalogMetaResponse, RecommendationResponse, budget_options

__all__ = [
    "INGEST_INSTRUCTION",
    "app",
    "ensure_catalog",
    "get_ranker_budget",
    "get_ranker_post",
]


def ensure_catalog(path: Path | None = None) -> Catalog:
    """Load the cleaned catalog or refuse to serve."""
    catalog_path = settings.catalog_path if path is None else path
    return load_catalog(catalog_path)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.catalog = ensure_catalog()
    yield


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Restaurant Recommendation System", lifespan=lifespan)


def add_cors(
    application: FastAPI,
    *,
    origins: tuple[str, ...] = (),
    origin_regex: str = "",
) -> None:
    """Allow the Vercel page to call this API. Same-origin use needs no origins."""
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_origin_regex=origin_regex or None,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )


add_cors(
    app,
    origins=settings.cors_origins,
    origin_regex=settings.cors_origin_regex,
)


@app.get("/")
def read_index() -> FileResponse:
    """The search page. Localities and results come from the API, not this file."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def read_health() -> dict[str, object]:
    """Liveness after the catalog has loaded. This route does not call a model."""
    catalog: Catalog = app.state.catalog
    return {"status": "ok", "restaurants": catalog.restaurant_count()}


@app.get("/api/meta", response_model=CatalogMetaResponse)
def read_meta() -> CatalogMetaResponse:
    """Localities and cuisines for the preference form. This route does not call a model."""
    catalog: Catalog = app.state.catalog
    return CatalogMetaResponse(
        localities=catalog.list_localities(),
        cuisines=catalog.list_cuisines(),
        budgets=budget_options(),
        default_min_rating=DEFAULT_MIN_RATING,
    )


def get_ranker_post() -> Callable[..., httpx.Response] | None:
    """Chat HTTP call. Tests replace this so a search never reaches Groq."""
    return None


def get_ranker_budget() -> TokenBudget | None:
    """Shared limiter in production. Tests pass a private budget."""
    return None


def _bad_request(
    detail: str,
    *,
    field: str | None = None,
    suggestions: list[str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "detail": detail,
        "suggestions": list(suggestions or [])[:5],
    }
    if field is not None:
        body["field"] = field
    return JSONResponse(status_code=400, content=body)


def _validation_response(exc: ValidationError) -> JSONResponse:
    errors = exc.errors()
    field = None
    if errors:
        location = errors[0].get("loc") or ()
        if location:
            field = str(location[-1])
    return _bad_request("Invalid preferences.", field=field)


def _recommendation_body(result: RecommendationResponse) -> dict[str, object]:
    """JSON for a search. An empty shortlist leaves `explanation_source` out."""
    body = result.model_dump(mode="json")
    if result.explanation_source is None:
        body.pop("explanation_source", None)
    return body


@app.post("/api/recommendations", response_model=RecommendationResponse)
async def create_recommendations(
    request: Request,
    post: Annotated[Callable[..., httpx.Response] | None, Depends(get_ranker_post)],
    budget: Annotated[TokenBudget | None, Depends(get_ranker_budget)],
) -> JSONResponse:
    """Validate, filter, rank, and join each card to the catalog loaded at startup."""
    catalog: Catalog = request.app.state.catalog
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _bad_request("Request body must be JSON.")
    try:
        result = recommend(catalog, payload, post=post, budget=budget)
    except ValidationError as exc:
        return _validation_response(exc)
    except PreferenceError as exc:
        return _bad_request(str(exc), field=exc.field, suggestions=exc.suggestions)
    return JSONResponse(status_code=200, content=_recommendation_body(result))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
