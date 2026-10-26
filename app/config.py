"""Runtime configuration.

Budget bands and relaxation rules live here so later phases can share one source.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "data" / "restaurants.parquet"
ENV_PATH = PROJECT_ROOT / ".env"

MAX_TOP_N = 8
PREFERENCE_TEXT_CAP = 300
EXPLANATION_LENGTH_CAP = 600
MIN_MATCHES_BEFORE_RELAX = 3
RATING_RELAX_STEP = 0.5
DEFAULT_MIN_RATING = 0.0
DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"

# Documented Groq limits for openai/gpt-oss-120b. Reasoning tokens count.
GROQ_REQUESTS_PER_MINUTE = 30
GROQ_REQUESTS_PER_DAY = 1_000
GROQ_TOKENS_PER_MINUTE = 8_000
GROQ_TOKENS_PER_DAY = 200_000

# Inclusive cost-for-two bounds in Indian rupees. High has no upper bound.
BUDGET_BANDS: dict[str, tuple[int, int | None]] = {
    "low": (0, 500),
    "medium": (501, 1000),
    "high": (1001, None),
}

# Bands allowed after one budget relaxation. Location is never widened.
ADJACENT_BUDGETS: dict[str, tuple[str, ...]] = {
    "low": ("low", "medium"),
    "medium": ("low", "medium", "high"),
    "high": ("medium", "high"),
}

RELAXATION_ORDER: tuple[str, ...] = (
    "budget_widened",
    "cuisine_dropped",
    "min_rating_lowered",
)


class ConfigError(ValueError):
    """Raised when an environment variable cannot be used as configuration."""


class Settings(BaseModel):
    """Process settings loaded from the environment."""

    model_config = ConfigDict(frozen=True)

    llm_api_key: str = ""
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    candidate_limit: int = 15
    default_top_n: int = 5
    max_top_n: int = MAX_TOP_N
    llm_timeout_seconds: float = 20
    preference_text_cap: int = PREFERENCE_TEXT_CAP
    explanation_length_cap: int = EXPLANATION_LENGTH_CAP
    min_matches_before_relax: int = MIN_MATCHES_BEFORE_RELAX
    rating_relax_step: float = RATING_RELAX_STEP
    budget_bands: dict[str, tuple[int, int | None]] = Field(
        default_factory=lambda: dict(BUDGET_BANDS)
    )
    adjacent_budgets: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: dict(ADJACENT_BUDGETS)
    )
    relaxation_order: tuple[str, ...] = RELAXATION_ORDER
    catalog_path: Path = CATALOG_PATH
    project_root: Path = PROJECT_ROOT
    cors_origins: tuple[str, ...] = ()
    cors_origin_regex: str = ""


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into the environment without overriding existing values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _read_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}.") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer, got {value}.")
    return value


def _read_positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive number, got {raw!r}.") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be a positive number, got {value}.")
    return value


def _read_csv(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _read_cors_origin_regex() -> str:
    raw = os.environ.get("CORS_ORIGIN_REGEX")
    if raw is None or raw.strip() == "":
        return ""
    pattern = raw.strip()
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConfigError(
            f"CORS_ORIGIN_REGEX is not a valid regular expression, got {pattern!r}."
        ) from exc
    return pattern


def _read_text(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def load_settings(*, env_file: Path | None = ENV_PATH) -> Settings:
    """Build settings from the environment. A missing env file uses defaults."""
    if env_file is not None:
        _load_env_file(env_file)

    default_top_n = _read_positive_int("DEFAULT_TOP_N", 5)
    if default_top_n > MAX_TOP_N:
        raise ConfigError(
            f"DEFAULT_TOP_N must be less than or equal to {MAX_TOP_N}, got {default_top_n}."
        )

    base_url = _read_text("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).rstrip("/")

    return Settings(
        llm_api_key=_read_text("LLM_API_KEY", ""),
        llm_base_url=base_url,
        llm_model=_read_text("LLM_MODEL", DEFAULT_LLM_MODEL),
        candidate_limit=_read_positive_int("CANDIDATE_LIMIT", 15),
        default_top_n=default_top_n,
        llm_timeout_seconds=_read_positive_float("LLM_TIMEOUT_SECONDS", 20),
        cors_origins=_read_csv("CORS_ORIGINS"),
        cors_origin_regex=_read_cors_origin_regex(),
    )


settings = load_settings()
