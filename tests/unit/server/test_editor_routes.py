"""编辑服务契约与真实 ty 进程的端到端检查."""

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from axile.server.api.routes import editor


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(editor.router)
    with TestClient(app) as value:
        yield value


def request(socket, identifier, method, params):
    socket.send_json({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
    while True:
        message = socket.receive_json()
        if message.get("id") == identifier:
            assert "error" not in message, message
            return message["result"]


def initialize(socket):
    session = socket.receive_json()
    capabilities = request(
        socket,
        1,
        "initialize",
        {
            "capabilities": {
                "textDocument": {
                    "completion": {"completionItem": {"snippetSupport": True}},
                    "diagnostic": {},
                    "hover": {"contentFormat": ["plaintext"]},
                    "semanticTokens": {
                        "requests": {"full": True},
                        "tokenTypes": ["class", "function", "variable", "parameter"],
                        "tokenModifiers": [],
                        "formats": ["relative"],
                    },
                    "inlayHint": {},
                    "foldingRange": {},
                    "codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": ["quickfix"]}}},
                }
            },
        },
    )
    socket.send_json({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    return session, capabilities


def open_document(socket, uri, code):
    socket.send_json(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": code},
            },
        }
    )


def test_formatting_and_syntax_errors(client):
    response = client.post("/editor/format", json={"code": 'x={"中文":1}\n'})
    assert response.status_code == 200
    assert response.json()["code"] == 'x = {"中文": 1}\n'
    assert client.post("/editor/format", json={"code": "def broken("}).status_code == 422


def test_source_access_is_read_only_and_scoped(client, tmp_path):
    source = Path(editor.__file__).resolve()
    assert client.get("/editor/source", params={"uri": source.as_uri()}).status_code == 200
    assert client.get("/editor/source", params={"uri": "file:///etc/passwd"}).status_code == 403
    assert client.get("/editor/source", params={"uri": (tmp_path / "secret.py").as_uri()}).status_code == 403


def test_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/editor/lsp", headers={"origin": "https://unrelated.example"}):
            pass


def test_lsp_features_and_session_cleanup(client):
    code = 'from axile.server.context import Context\n\ndef calculate_portfolio(context: Context) -> dict[str, float]:\n    price = context.get_price("中文")\n    return {"rb2610": price}\n\nwrong: int = "bad"\n'
    with client.websocket_connect("/editor/lsp") as socket:
        session, capabilities = initialize(socket)
        uri = session["uri"]
        params = {"textDocument": {"uri": uri}}
        open_document(socket, uri, code)
        diagnostic = request(socket, 2, "textDocument/diagnostic", params)
        assert any("int" in item["message"] for item in diagnostic["items"]), diagnostic
        assert not any("unresolved-import" == item.get("code") for item in diagnostic["items"]), diagnostic
        socket.send_json(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {
                    "textDocument": {"uri": uri, "version": 2},
                    "contentChanges": [{"text": code.replace('context.get_price("中文")', "context.get_")}],
                },
            }
        )
        completion = request(socket, 3, "textDocument/completion", {**params, "position": {"line": 3, "character": 24}})
        items = completion["items"] if isinstance(completion, dict) else completion
        assert any(item["label"] == "get_price" for item in items), completion
        socket.send_json(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didChange",
                "params": {"textDocument": {"uri": uri, "version": 3}, "contentChanges": [{"text": code}]},
            }
        )
        hover = request(socket, 4, "textDocument/hover", {**params, "position": {"line": 3, "character": 24}})
        assert hover and "get_price" in str(hover), hover
        signature = request(
            socket, 5, "textDocument/signatureHelp", {**params, "position": {"line": 3, "character": 31}}
        )
        assert signature and signature["signatures"], signature
        definition = request(socket, 6, "textDocument/definition", {**params, "position": {"line": 3, "character": 24}})
        assert definition and "context.py" in str(definition), definition
        references = request(
            socket,
            7,
            "textDocument/references",
            {**params, "position": {"line": 3, "character": 6}, "context": {"includeDeclaration": True}},
        )
        assert len(references) >= 2, references
        rename = request(
            socket,
            8,
            "textDocument/rename",
            {**params, "position": {"line": 3, "character": 6}, "newName": "latest_price"},
        )
        assert "latest_price" in str(rename), rename
        tokens = request(socket, 9, "textDocument/semanticTokens/full", params)
        assert tokens["data"], (tokens, capabilities)
        hints = request(
            socket,
            10,
            "textDocument/inlayHint",
            {**params, "range": {"start": {"line": 0, "character": 0}, "end": {"line": 7, "character": 0}}},
        )
        assert hints, hints
        folds = request(socket, 11, "textDocument/foldingRange", params)
        assert folds, folds
        fixes = request(
            socket,
            12,
            "textDocument/codeAction",
            {
                **params,
                "range": diagnostic["items"][0]["range"],
                "context": {"diagnostics": diagnostic["items"], "only": ["quickfix"]},
            },
        )
        assert fixes, fixes
    assert not Path(uri.removeprefix("file://")).parent.exists()
    assert not editor._sessions


def test_sessions_are_independent(client):
    with client.websocket_connect("/editor/lsp") as first, client.websocket_connect("/editor/lsp") as second:
        left, _ = initialize(first)
        right, _ = initialize(second)
        assert left["uri"] != right["uri"]
        open_document(first, left["uri"], 'value: int = "bad"')
        open_document(second, right["uri"], "value: int = 1")
        assert request(first, 2, "textDocument/diagnostic", {"textDocument": {"uri": left["uri"]}})["items"]
        assert not request(second, 2, "textDocument/diagnostic", {"textDocument": {"uri": right["uri"]}})["items"]


def test_unicode_lsp_framing():
    async def check():
        reader = asyncio.StreamReader()
        data = '{"text":"中文😀"}'.encode()
        reader.feed_data(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        assert await editor.read_message(reader) == data.decode()

    asyncio.run(check())


def test_foreign_document_rejected():
    with pytest.raises(ValueError, match="当前编辑会话"):
        editor.validate_message(
            {"method": "textDocument/didOpen", "params": {"textDocument": {"uri": "file:///tmp/other.py"}}},
            "file:///tmp/mine.py",
        )
