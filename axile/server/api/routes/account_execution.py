"""账户执行控制相关路由."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import func, select

from axile.channels import get_channel
from axile.domain.execution import ExecutionTaskStatus
from axile.server.api.deps import SchedDep, SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.api.routes.portfolio import resolve_portfolio_target
from axile.server.context import Context
from axile.server.core.db import SessionLocal
from axile.server.db.models import (
    ExecutionArtifact,
    ExecutionArtifactListPublic,
    ExecutionArtifactPublic,
    ExecutionEvent,
    ExecutionEventListPublic,
    ExecutionEventPublic,
    ExecutionStatusPublic,
    ExecutionTerminateRequest,
    ExecutionTerminateResponse,
    ExecutionTriggerResponse,
    Portfolio,
    TargetWeightSnapshot,
    TargetWeightSnapshotPublic,
)
from axile.server.execution.lifecycle import enqueue_empty_positions, enqueue_execute_trade
from axile.server.execution.live import live_hub
from axile.server.execution.rebalance import _normalize_rebalance_target
from axile.server.execution.registry import (
    AccountExecutionAlreadyRunningError,
    clear_target_refresh,
    get_execution_status,
    get_queued_execution_id,
    get_running_execution_id,
    terminate_running_account_execution,
    try_register_target_refresh,
)
from axile.server.execution.scheduler import delete_job
from axile.server.integrity import plan_executable_target
from axile.server.repositories import (
    get_latest_portfolio_id_by_account_id,
    get_recent_account_asset_snapshots,
)
from axile.server.target_weight_snapshots import (
    append_target_weight_snapshot,
    get_latest_account_target_snapshot,
    target_snapshot_public,
)

router = APIRouter()


async def _latest_book(session: SessionDep, account_id: int) -> tuple[list[object], float]:
    """读取账户最近一条资产快照的持仓与权益；无快照时视为空仓."""
    snapshots = await get_recent_account_asset_snapshots(session, account_id, limit=1)
    if not snapshots:
        return [], 0.0
    assets = snapshots[0].assets if isinstance(snapshots[0].assets, dict) else {}
    raw_positions = assets.get("positions")
    positions = raw_positions if isinstance(raw_positions, list) else []
    try:
        equity = float(assets.get("total_asset") or 0.0)
    except (TypeError, ValueError):
        equity = 0.0
    return positions, equity


def _account_target_public(
    account: object,
    snapshot: TargetWeightSnapshot | None,
    positions: list[object],
    equity: float,
) -> TargetWeightSnapshotPublic:
    """账户目标快照：权重 key 与持仓对齐，并附带渠道量化后的目标数量."""
    if snapshot is None:
        return TargetWeightSnapshotPublic()
    plugin = get_channel(getattr(account, "trade_channel"))
    plan = plan_executable_target(
        positions,
        snapshot.normalized_weights or {},
        equity,
        canonicalize_symbol=plugin.canonicalize_symbol,
        quantize_target_quantity=plugin.quantize_target_quantity,
    )
    return target_snapshot_public(
        snapshot,
        weight_kind="normalized",
        weights=plan.weights,
        quantities=plan.quantities,
    )


def _account_route_module() -> Any:
    from axile.server.api.routes import account as account_routes

    return account_routes


@router.post("/execute/{account_id}", response_model=ExecutionTriggerResponse)
async def execute(session: SessionDep, account_id: int) -> ExecutionTriggerResponse:
    """异步触发立即执行，并返回可用于轮询的执行标识."""
    await _get_account_or_404(session, account_id)

    try:
        submitted = await enqueue_execute_trade(account_id)
    except AccountExecutionAlreadyRunningError as exc:
        logger.warning(f"执行交易冲突: account_id={account_id}, error={exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(f"执行交易失败: account_id={account_id}, error={exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="执行失败, 详情请看飞书信息或日志",
        ) from exc

    execution_id = submitted.execution_id
    if execution_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"账户 {account_id} 已有调仓任务在执行中",
        )
    return ExecutionTriggerResponse(
        message="已与等待中的执行合并" if submitted.outcome == "coalesced" else "已触发",
        execution_id=execution_id,
        account_id=account_id,
        accepted=submitted.outcome if submitted.outcome in {"created", "coalesced"} else "created",
    )


@router.get("/{account_id}/target_snapshot", response_model=TargetWeightSnapshotPublic)
async def account_target_snapshot(session: SessionDep, account_id: int) -> TargetWeightSnapshotPublic:
    """只读账户当前绑定组合下最近成功计算的目标快照."""
    account = await _get_account_or_404(session, account_id)
    portfolio_id = await get_latest_portfolio_id_by_account_id(session, account_id)
    if portfolio_id is None:
        return TargetWeightSnapshotPublic()
    snapshot = await get_latest_account_target_snapshot(session, account_id, portfolio_id)
    positions, equity = await _latest_book(session, account_id)
    return _account_target_public(account, snapshot, positions, equity)


@router.post("/{account_id}/target_snapshot/refresh", response_model=TargetWeightSnapshotPublic)
async def refresh_account_target_snapshot(session: SessionDep, account_id: int) -> TargetWeightSnapshotPublic:
    """按用户请求使用真实账户上下文重新计算并保存目标权重."""
    account = await _get_account_or_404(session, account_id)
    portfolio_id = await get_latest_portfolio_id_by_account_id(session, account_id)
    if portfolio_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户未绑定组合")
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户绑定的组合不存在")
    if not try_register_target_refresh(portfolio_id, account_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户正在执行或刷新，请稍后再试")

    try:
        async with SessionLocal() as context_session:
            raw_target = await resolve_portfolio_target(
                portfolio,
                Context(session=context_session, account_id=account_id),
            )
        normalized_target = _normalize_rebalance_target(account, raw_target)
        snapshot = await append_target_weight_snapshot(
            session,
            portfolio_id=portfolio_id,
            account_id=account_id,
            raw_weights=raw_target,
            normalized_weights=normalized_target,
            source="manual",
        )
        positions, equity = await _latest_book(session, account_id)
        return _account_target_public(account, snapshot, positions, equity)
    finally:
        clear_target_refresh(portfolio_id, account_id)


# 心跳间隔（秒）：无事件时也定期发注释帧，避免中间层因空闲断连。
_SSE_HEARTBEAT_SEC = 15.0


def _sse_frame(event: str, data: object) -> str:
    """把一帧序列化为 SSE 线格式（``event:`` + ``data:`` + 空行）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/executions/stream")
async def executions_stream(request: Request) -> StreamingResponse:
    """
    执行实时态 SSE 流（全账户）.

    连上先推一帧 ``snapshot``（当前所有在途执行 + 阶段），随后逐帧转发实时
    ``event``；空闲时按 :data:`_SSE_HEARTBEAT_SEC` 发心跳注释保活。数据方向纯为
    server→client，故用 SSE 而非 WebSocket。前端按 ``account_id`` 自行过滤。

    Notes
    -----
    必须声明在 ``/executions/{execution_id}`` 之前，否则 ``stream`` 会被当作
    ``execution_id`` 路径参数捕获。
    """

    async def _event_stream() -> AsyncIterator[str]:
        async with live_hub.subscribe() as queue:
            # 首帧：当前在途执行快照，保证「刚连上」即正确（冷渲染与 REST 同源）。
            yield _sse_frame("snapshot", live_hub.snapshot())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_SEC)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                event_name = cast("str", frame.get("type", "event"))
                yield _sse_frame(event_name, frame)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭反向代理缓冲，确保逐帧实时下发。
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/executions/{execution_id}", response_model=ExecutionStatusPublic)
async def execution_status(execution_id: str) -> ExecutionStatusPublic:
    """查询指定执行标识对应的任务状态."""
    status_payload = await get_execution_status(execution_id)
    if status_payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="执行不存在",
        )

    return ExecutionStatusPublic.model_validate(status_payload)


@router.post("/{account_id}/terminate", response_model=ExecutionTerminateResponse)
async def terminate_account_execution(
    session: SessionDep,
    account_id: int,
    payload: ExecutionTerminateRequest,
    response: Response,
) -> ExecutionTerminateResponse:
    """终止账户当前正在运行的执行任务."""
    await _get_account_or_404(session, account_id)

    running_execution_id = get_running_execution_id(account_id) or get_queued_execution_id(account_id)
    current_status = None if running_execution_id is None else await get_execution_status(running_execution_id)
    current_task_status = None if current_status is None else cast("ExecutionTaskStatus", current_status["status"])

    state = await terminate_running_account_execution(
        account_id,
        reason=payload.reason,
        mode=payload.mode,
    )
    if state is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户当前没有活跃执行")

    response_status = status.HTTP_200_OK
    if current_task_status in {ExecutionTaskStatus.QUEUED, ExecutionTaskStatus.RUNNING}:
        response_status = status.HTTP_202_ACCEPTED
    response.status_code = response_status

    return ExecutionTerminateResponse(
        message="已受理终止请求",
        account_id=account_id,
        execution_id=state.execution_id,
        status=state.status,
    )


@router.get("/executions/{execution_id}/events", response_model=ExecutionEventListPublic)
async def execution_events(
    session: SessionDep,
    execution_id: str,
    skip: int = 0,
    limit: int = 200,
) -> ExecutionEventListPublic:
    """查询指定执行标识对应的事件流."""
    count_stmt = select(func.count()).select_from(ExecutionEvent).where(ExecutionEvent.execution_id == execution_id)
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id)
        # 按 id（自增=落库/发生顺序）排序，而非 seq：终止类事件 seq=0 会排到 started(seq=1) 之前，
        # 令接口原始序列读作「先终止后开始」。id 单调递增即真实时序，正常事件的 seq 顺序与之一致。
        .order_by(cast("Any", ExecutionEvent.id))
        .offset(skip)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return ExecutionEventListPublic(
        data=[ExecutionEventPublic.model_validate(row) for row in rows],
        count=total,
    )


@router.get("/executions/{execution_id}/artifacts", response_model=ExecutionArtifactListPublic)
async def execution_artifacts(
    session: SessionDep,
    execution_id: str,
    skip: int = 0,
    limit: int = 100,
) -> ExecutionArtifactListPublic:
    """查询指定执行标识对应的执行附件."""
    count_stmt = (
        select(func.count()).select_from(ExecutionArtifact).where(ExecutionArtifact.execution_id == execution_id)
    )
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        select(ExecutionArtifact)
        .where(ExecutionArtifact.execution_id == execution_id)
        .order_by(cast("Any", ExecutionArtifact.id))
        .offset(skip)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return ExecutionArtifactListPublic(
        data=[ExecutionArtifactPublic.model_validate(row) for row in rows],
        count=total,
    )


@router.post("/empty_positions/{account_id}", response_model=ExecutionTriggerResponse)
async def empty_all_positions(
    session: SessionDep,
    sched: SchedDep,
    account_id: int,
    algorithm_method: str | None = None,
    algorithm_params: str | None = None,
) -> ExecutionTriggerResponse:
    """异步触发一键平仓，并返回可用于轮询的执行标识."""
    db_account = await _get_account_or_404(session, account_id)
    account_routes = _account_route_module()

    try:
        algorithm = account_routes._build_empty_positions_algorithm(
            algorithm_method=algorithm_method,
            algorithm_params=algorithm_params,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # 先停调度，再入队一次性清仓，避免 CRON 在人工清仓期间再次拉起执行。
    db_account.sqlmodel_update({"is_started": False})
    session.add(db_account)
    await session.commit()
    delete_job(sched, account_id)

    try:
        submitted = await enqueue_empty_positions(account_id, algorithm=algorithm)
    except AccountExecutionAlreadyRunningError as exc:
        logger.warning(f"清仓冲突: account_id={account_id}, error={exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(f"清仓失败: account_id={account_id}, error={exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="执行失败, 详情请看飞书信息或日志",
        ) from exc

    execution_id = submitted.execution_id
    if execution_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"账户 {account_id} 已有调仓任务在执行中",
        )
    return ExecutionTriggerResponse(
        message="已与等待中的清仓合并" if submitted.outcome == "coalesced" else "已触发清仓",
        execution_id=execution_id,
        account_id=account_id,
        accepted=submitted.outcome if submitted.outcome in {"created", "coalesced"} else "created",
    )
