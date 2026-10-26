"""The search page is served with the API. It does not call a model."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import add_cors, app


def test_index_serves_the_search_page() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Find a table" in page.text
        assert "/static/app.js" in page.text
        assert "/static/styles.css" in page.text

        script = client.get("/static/app.js")
        style = client.get("/static/styles.css")

    assert script.status_code == 200
    assert "innerHTML" not in script.text
    assert "insertAdjacentHTML" not in script.text
    assert "window.API_BASE" in script.text
    assert "/api/meta" in script.text
    assert "/api/recommendations" in script.text
    assert style.status_code == 200
    assert "#12110f" in style.text


def test_cors_echoes_a_vercel_origin_and_refuses_credentials() -> None:
    application = FastAPI()

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    add_cors(
        application,
        origins=("https://app.vercel.app",),
        origin_regex=r"https://.*\.vercel\.app",
    )

    with TestClient(application) as client:
        preview = client.get(
            "/api/health",
            headers={"Origin": "https://preview-abc.vercel.app"},
        )
        preflight = client.options(
            "/api/health",
            headers={
                "Origin": "https://app.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        other = client.get("/api/health", headers={"Origin": "https://evil.example"})

    assert preview.headers["access-control-allow-origin"] == "https://preview-abc.vercel.app"
    assert "access-control-allow-credentials" not in preview.headers
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://app.vercel.app"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert "content-type" in preflight.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in other.headers
