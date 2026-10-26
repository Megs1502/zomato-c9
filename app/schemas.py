"""Request and response models for the catalog and later recommendation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import (
    BUDGET_BANDS,
    DEFAULT_MIN_RATING,
    MAX_TOP_N,
    PREFERENCE_TEXT_CAP,
    settings,
)


class Restaurant(BaseModel):
    """One cleaned restaurant row from the parquet catalog."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    address: str = ""
    location: str = ""
    areas: list[str] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    cost_for_two: int | None = None
    rating: float | None = None
    votes: int = 0
    rest_type: list[str] = Field(default_factory=list)
    online_order: bool = False
    book_table: bool = False
    dish_liked: list[str] = Field(default_factory=list)
    listed_types: list[str] = Field(default_factory=list)
    review_snippet: str | None = None


class CatalogMetaResponse(BaseModel):
    """Values the preference form needs before a search."""

    localities: list[str]
    cuisines: list[str]
    budgets: list[str]
    default_min_rating: float = DEFAULT_MIN_RATING


def budget_options() -> list[str]:
    """Public budget names in display order. Missing cost is not a choice."""
    return [name for name in BUDGET_BANDS if name in {"low", "medium", "high"}]


class Preferences(BaseModel):
    """User choices before they are matched to catalog spellings."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    location: str = Field(min_length=1)
    budget: Literal["low", "medium", "high"]
    cuisine: str | None = None
    min_rating: float = Field(default=DEFAULT_MIN_RATING, ge=0, le=5)
    additional_preferences: str = Field(default="", max_length=PREFERENCE_TEXT_CAP)
    top_n: int = Field(default=settings.default_top_n, ge=1, le=MAX_TOP_N)

    @field_validator("location", mode="before")
    @classmethod
    def location_must_be_text(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("location is required")
        return value.strip()

    @field_validator("budget", mode="before")
    @classmethod
    def normalize_budget(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value

    @field_validator("cuisine", mode="before")
    @classmethod
    def blank_cuisine_means_any(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        return value

    @field_validator("min_rating", mode="before")
    @classmethod
    def min_rating_must_be_numeric(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("min_rating must be a number from 0 to 5")
        return value

    @field_validator("additional_preferences", mode="before")
    @classmethod
    def blank_preferences_are_empty(cls, value: object) -> object:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("additional_preferences must be text")
        return value.strip()

    @field_validator("top_n", mode="before")
    @classmethod
    def top_n_must_be_an_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("top_n must be an integer from 1 to 8")
        return value


class FiltersApplied(BaseModel):
    """Constraints that actually ran, including any relaxation."""

    model_config = ConfigDict(frozen=True)

    location: str
    budget: list[str]
    cuisine: str | None = None
    min_rating: float = DEFAULT_MIN_RATING
    relaxed: list[str] = Field(default_factory=list)


class Shortlist(BaseModel):
    """Capped candidates and the filters that produced them.

    `use_model` is false when the shortlist is empty. That path is guidance only.
    """

    model_config = ConfigDict(frozen=True)

    candidates: list[Restaurant]
    filters_applied: FiltersApplied
    candidate_count: int = Field(ge=0)
    summary: str | None = None
    use_model: bool


class RecommendationCard(BaseModel):
    """One ranked restaurant. Display fields come from the catalog, not the model text."""

    model_config = ConfigDict(frozen=True)

    rank: int
    id: str
    name: str
    cuisines: list[str]
    rating: float | None = None
    votes: int = 0
    cost_for_two: int | None = None
    address: str
    rest_type: list[str]
    online_order: bool
    book_table: bool
    explanation: str


class RecommendationResponse(BaseModel):
    """The body of POST /api/recommendations.

    `explanation_source` is omitted when the shortlist was empty and no model ran.
    `filters_applied.budget` is the list of bands that were actually used.
    """

    model_config = ConfigDict(frozen=True)

    summary: str
    explanation_source: Literal["llm", "fallback"] | None = None
    filters_applied: FiltersApplied
    candidate_count: int = Field(ge=0)
    recommendations: list[RecommendationCard]
