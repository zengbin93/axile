"""账户资产查询的 worker 协议测试."""

from __future__ import annotations

import asyncio

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.server.execution.worker_backend import worker as worker_entry
from axile.server.execution.worker_backend.manager import WorkerBackendExecutionError, WorkerBackendManager
from axile.server.execution.worker_backend.protocol import (
    WorkerBackendErrorPayload,
    WorkerBackendRequest,
    WorkerBackendResponse,
)
from axile.server.execution.worker_backend.worker_state import _WorkerBackendState
from tests.unit.server._execution_test_support import build_account


class _Executor:
    def get_account_assets(self) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(
            available_cash=750.0,
            total_asset=1000.0,
            market_value=250.0,
            positions=[],
        )


def test_worker_get_account_assets_command_returns_unified_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    account = build_account(id=61)
    request = WorkerBackendRequest(
        request_id="asset-request",
        command="get_account_assets",
        account_payload=account.model_dump(mode="json"),
        execution_id=None,
        payload={},
    )
    monkeypatch.setattr(worker_entry, "_resolve_prepared_executor", lambda **_kwargs: _Executor())
    monkeypatch.setattr(worker_entry, "_finalize_executor", lambda _executor: None)

    response = worker_entry._handle_worker_request(request, _WorkerBackendState())

    assert response.kind == "result"
    assert response.output_payload is not None
    assert response.output_payload["total_asset"] == 1000.0


def test_manager_get_account_assets_validates_worker_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    account = build_account(id=62)
    manager = WorkerBackendManager()

    def _request(_account_id: int, request: WorkerBackendRequest, _timeout: float) -> WorkerBackendResponse:
        assert request.command == "get_account_assets"
        return WorkerBackendResponse(
            request_id=request.request_id,
            kind="result",
            output_payload={
                "available_cash": 800.0,
                "total_asset": 1200.0,
                "market_value": 400.0,
                "positions": [],
            },
        )

    monkeypatch.setattr(manager, "_request_blocking", _request)
    assets = asyncio.run(manager.get_account_assets(account))

    assert assets.total_asset == 1200.0
    assert assets.available_cash == 800.0


def test_manager_does_not_drop_worker_for_other_ctp_error(monkeypatch: pytest.MonkeyPatch) -> None:
    account = build_account(id=62)
    manager = WorkerBackendManager()
    dropped: list[int] = []

    def _request(_account_id: int, request: WorkerBackendRequest, _timeout: float) -> WorkerBackendResponse:
        return WorkerBackendResponse(
            request_id=request.request_id,
            kind="error",
            channel_type=TradeChannel.CTP,
            error=WorkerBackendErrorPayload(type="ctp_request_error", message="boom"),
        )

    async def _drop(account_id: int) -> None:
        dropped.append(account_id)

    monkeypatch.setattr(manager, "_request_blocking", _request)
    monkeypatch.setattr(manager, "drop_account", _drop)

    with pytest.raises(WorkerBackendExecutionError, match="boom"):
        asyncio.run(manager.get_account_assets(account))

    assert dropped == []
