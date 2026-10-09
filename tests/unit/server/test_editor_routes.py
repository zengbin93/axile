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


@pytest.mark.parametrize(
    ("kind", "name", "type_name"),
    [
        ("portfolio", "calculate_portfolio", "Context"),
        ("account_notification", "notify", "AccountNotificationContext"),
        ("system_notification", "notify", "SystemNotificationContext"),
    ],
)
def test_contract_reports_entry_and_annotation_fix(client, kind, name, type_name):
    missing = client.post("/editor/contract", json={"kind": kind, "code": "x = 1\n"}).json()
    assert name in missing["diagnostics"][0]["message"]
    code = f"def {name}(context):\n    return {{}}\n"
    report = client.post("/editor/contract", json={"kind": kind, "code": code}).json()
    assert len(report["diagnostics"]) == 1
    assert report["diagnostics"][0]["severity"] == 3
    assert report["fixes"][0]["edits"][0]["newText"] == f": {type_name}"
    assert report["fixes"][0]["edits"][1]["newText"].endswith(f"import {type_name}\n")


def test_contract_rejects_uncallable_signatures(client):
    for code in ("def notify(*, context):\n    pass\n", "async def notify(*, context):\n    pass\n"):
        report = client.post("/editor/contract", json={"kind": "account_notification", "code": code}).json()
        assert report["diagnostics"][0]["severity"] == 1
    code = "from __future__ import annotations\ndef calculate_portfolio(context):\n    return {}\n"
    report = client.post("/editor/contract", json={"kind": "portfolio", "code": code}).json()
    assert report["fixes"][0]["edits"][1]["range"]["start"]["line"] == 1


def test_contract_fix_uses_utf16_columns(client):
    code = "def notify(上下文):\n    pass\n"
    report = client.post("/editor/contract", json={"kind": "system_notification", "code": code}).json()
    assert report["fixes"][0]["edits"][0]["range"]["start"]["character"] == len("def notify(上下文")


def test_typed_notification_context_is_checked_by_ty(client):
    code = (
        "from axile.common.notification_context import AccountNotificationContext\n"
        "def notify(context: AccountNotificationContext) -> None:\n"
        '    count: str = context["summary"]["trade_count"]\n'
    )
    with client.websocket_connect("/editor/lsp") as socket:
        session, _ = initialize(socket)
        open_document(socket, session["uri"], code)
        report = request(socket, 31, "textDocument/diagnostic", {"textDocument": {"uri": session["uri"]}})
        assert any("str" in item["message"] and "int" in item["message"] for item in report["items"]), report


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
        assert capabilities["capabilities"].get("documentSymbolProvider")
        symbols = request(socket, 20, "textDocument/documentSymbol", params)
        assert any(item["name"] == "calculate_portfolio" for item in symbols)
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


def test_external_source_supports_readonly_definition_navigation(client):
    source = Path(editor.__file__).resolve().parents[2] / "context.py"
    source_uri = source.as_uri()
    text = source.read_text(encoding="utf-8")
    with client.websocket_connect("/editor/lsp") as socket:
        session, _ = initialize(socket)
        open_document(socket, source_uri, text)
        definition = request(
            socket,
            32,
            "textDocument/definition",
            {"textDocument": {"uri": source_uri}, "position": {"line": 6, "character": 80}},
        )
        assert "unified_account_assets.py" in str(definition), definition
        with pytest.raises(ValueError, match="当前编辑会话"):
            editor.validate_message(
                {"method": "textDocument/didChange", "params": {"textDocument": {"uri": source_uri}}},
                session["uri"],
            )
        with pytest.raises(ValueError, match="当前编辑会话"):
            editor.validate_message(
                {"method": "textDocument/rename", "params": {"textDocument": {"uri": source_uri}}},
                session["uri"],
            )
        with pytest.raises(ValueError, match="内容与服务器文件不一致"):
            editor.validate_message(
                {"method": "textDocument/didOpen", "params": {"textDocument": {"uri": source_uri, "text": "changed"}}},
                session["uri"],
            )


@pytest.mark.parametrize("kind", ["account_notification", "system_notification"])
def test_notification_editor_accepts_async_and_rejects_generators(client, kind):
    report = client.post("/editor/contract", json={"kind": kind, "code": "async def notify(context):\n    pass"}).json()
    assert not any(item["severity"] == 1 for item in report["diagnostics"])
    for code in ("def notify(context):\n    yield 1", "async def notify(context):\n    yield 1"):
        report = client.post("/editor/contract", json={"kind": kind, "code": code}).json()
        assert any("生成器" in item["message"] and item["severity"] == 1 for item in report["diagnostics"])
    code = "def notify(context):\n    def items():\n        yield 1\n    list(items())"
    report = client.post("/editor/contract", json={"kind": kind, "code": code}).json()
    assert not any(item["severity"] == 1 for item in report["diagnostics"])


def test_portfolio_editor_still_rejects_async(client):
    report = client.post(
        "/editor/contract", json={"kind": "portfolio", "code": "async def calculate_portfolio(context):\n    return {}"}
    ).json()
    assert any("同步函数" in item["message"] and item["severity"] == 1 for item in report["diagnostics"])


@pytest.mark.parametrize("wrong_type", [False, True])
def test_notification_execution_fields_are_checked_by_ty(client, wrong_type):
    code = (
        "from axile.common.notification_context import AccountNotificationContext\n"
        "async def notify(context: AccountNotificationContext) -> None:\n"
        '    if context["execution"] is None:\n        return\n'
        '    kind: str | None = context["execution"]["kind"]\n'
        '    trigger: str | None = context["execution"]["trigger_source"]\n'
        '    notified: str = context["execution"]["notified_at"]\n'
        '    elapsed: float = context["execution"]["execution_time"]\n'
        '    reason: str | None = context["execution"]["outcome_reason"]\n'
        '    channel: str = context["execution"]["channel_type"]\n'
        "    print(kind, trigger, notified, elapsed, reason, channel)\n"
    )
    if wrong_type:
        code = code.replace("elapsed: float", "elapsed: str")
    with client.websocket_connect("/editor/lsp") as socket:
        session, _ = initialize(socket)
        open_document(socket, session["uri"], code)
        report = request(socket, 31, "textDocument/diagnostic", {"textDocument": {"uri": session["uri"]}})
        if wrong_type:
            assert any("float" in item["message"] and "str" in item["message"] for item in report["items"]), report
        else:
            assert not report["items"], report
