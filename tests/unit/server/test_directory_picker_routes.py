"""本机目录选择器只读 API 测试."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from axile.server.api.routes import utils


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(utils.router, prefix="/api/v1")
    return TestClient(app)


def test_directory_picker_lists_only_directories(tmp_path) -> None:
    (tmp_path / "Beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "ignored.txt").touch()

    response = _client().get("/api/v1/utils/directories", params={"path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(tmp_path.resolve())
    assert [item["name"] for item in payload["entries"]] == ["alpha", "Beta"]
    assert payload["parent"] == str(tmp_path.resolve().parent)


def test_directory_picker_rejects_relative_and_missing_paths(tmp_path) -> None:
    client = _client()

    assert client.get("/api/v1/utils/directories", params={"path": "relative"}).status_code == 400
    assert (
        client.get(
            "/api/v1/utils/directories",
            params={"path": str(tmp_path / "missing")},
        ).status_code
        == 404
    )


def test_directory_picker_roots_are_lazy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(utils, "_directory_roots", lambda: [tmp_path])

    response = _client().get("/api/v1/utils/directories")

    assert response.json() == {
        "path": None,
        "parent": None,
        "entries": [{"name": tmp_path.name, "path": str(tmp_path)}],
    }
