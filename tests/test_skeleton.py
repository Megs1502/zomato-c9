"""Exit checks for the project skeleton."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_TOP_N, ConfigError, load_settings
from app.main import INGEST_INSTRUCTION, app, ensure_catalog


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "CANDIDATE_LIMIT",
        "DEFAULT_TOP_N",
        "LLM_TIMEOUT_SECONDS",
        "CORS_ORIGINS",
        "CORS_ORIGIN_REGEX",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(env_file=None)

    assert settings.llm_api_key == ""
    assert settings.llm_base_url == "https://api.groq.com/openai/v1"
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.candidate_limit == 15
    assert settings.default_top_n == 5
    assert settings.max_top_n == MAX_TOP_N
    assert settings.llm_timeout_seconds == 20
    assert settings.preference_text_cap == 300
    assert settings.explanation_length_cap == 600
    assert settings.budget_bands["low"] == (0, 500)
    assert settings.budget_bands["medium"] == (501, 1000)
    assert settings.budget_bands["high"] == (1001, None)
    assert settings.relaxation_order == (
        "budget_widened",
        "cuisine_dropped",
        "min_rating_lowered",
    )
    assert settings.cors_origins == ()
    assert settings.cors_origin_regex == ""


def test_cors_settings_parse_origins_and_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://app.vercel.app, https://food.example")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")

    settings = load_settings(env_file=None)

    assert settings.cors_origins == ("https://app.vercel.app", "https://food.example")
    assert settings.cors_origin_regex == r"https://.*\.vercel\.app"


def test_cors_origin_regex_must_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGIN_REGEX", "[")
    with pytest.raises(ConfigError, match="CORS_ORIGIN_REGEX"):
        load_settings(env_file=None)


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("CANDIDATE_LIMIT", "0"),
        ("CANDIDATE_LIMIT", "-3"),
        ("CANDIDATE_LIMIT", "many"),
        ("DEFAULT_TOP_N", "0"),
        ("DEFAULT_TOP_N", "nope"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "-1"),
        ("LLM_TIMEOUT_SECONDS", "fast"),
    ],
)
def test_invalid_numeric_settings_name_the_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, raw: str
) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ConfigError, match=name):
        load_settings(env_file=None)


def test_default_top_n_cannot_exceed_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_TOP_N", str(MAX_TOP_N + 1))
    with pytest.raises(ConfigError, match="DEFAULT_TOP_N"):
        load_settings(env_file=None)


def test_missing_catalog_tells_the_operator_to_run_ingest(tmp_path: Path) -> None:
    missing = tmp_path / "restaurants.parquet"
    with pytest.raises(RuntimeError, match="python -m pipeline.ingest") as exc_info:
        ensure_catalog(missing)
    assert INGEST_INSTRUCTION in str(exc_info.value)


def test_unreadable_catalog_tells_the_operator_to_run_ingest(tmp_path: Path) -> None:
    catalog = tmp_path / "restaurants.parquet"
    catalog.write_bytes(b"placeholder")
    with pytest.raises(RuntimeError, match="python -m pipeline.ingest") as exc_info:
        ensure_catalog(catalog)
    assert INGEST_INSTRUCTION in str(exc_info.value)


def test_app_startup_fails_when_the_catalog_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "app.main.settings",
        load_settings(env_file=None).model_copy(
            update={"catalog_path": tmp_path / "restaurants.parquet"}
        ),
    )
    with pytest.raises(RuntimeError, match="python -m pipeline.ingest"):
        with TestClient(app):
            pass
