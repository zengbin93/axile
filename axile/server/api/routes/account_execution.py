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

from axile.domain.execution import ExecutionTaskStatus
from axile.server.api.deps import SchedDep, SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.api.routes.portfolio import resolve_portfolio_target
from axile.server.context import Context
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
)
from axile.server.execution.lifecycle import enqueue_empty_positions, enqueue_execute_trade
from axile.server.execution.live import live_hub
from axile.server.execution.rebalance import _normalize_rebalance_target
from axile.server.execution.registry import (
    AccountExecutionAlreadyRunningError,
    get_execution_status,
    get_running_execution_id,
    terminate_running_account_execution,
)
from axile.server.execution.scheduler import delete_job
from axile.server.repositories import get_latest_portfolio_id_by_account_id

router = APIRouter()


def _account_route_module() -> Any:
    from axile.server.api.routes import account as account_routes

    return account_routes


@router.post("/execute/{account_id}", response_model=ExecutionTriggerResponse)
async def execute(session: SessionDep, account_id: int) -> ExecutionTriggerResponse:
    """异步触发立即执行，并返回可用于轮询的执行标识."""
    await _get_account_or_404(session, account_id)

    try:
        execution_id = await enqueue_execute_trade(account_id)
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

    return ExecutionTriggerResponse(
        message="已触发",
        execution_id=execution_id,
        account_id=account_id,
    )


@router.get("/{account_id}/target_weights")
async def account_target_weights(session: SessionDep, account_id: int) -> dict[str, float]:
    """
    返回账户当前的**执行器口径**目标持仓权重.

    与组合级 ``/portfolio/latest_weights`` 的区别: 这里叠加了账户的多空杠杆与
    ``weight_precision`` 精度, 复用执行器真正使用的 :func:`_normalize_rebalance_target`,
    因此展示口径与实际下单口径完全一致——持仓明细据此判定「到位/待调整」时不再因杠杆
    缩放而误判。绑定组合的解析同样走执行器的 :func:`get_latest_portfolio_id_by_account_id`,
    未绑定组合时返回空映射交由前端降级。

    Parameters
    ----------
    session : SessionDep
        数据库会话。
    account_id : int
        账户 ID。

    Returns
    -------
    dict[str, float]
        ``symbol -> 目标权重``（已含杠杆与精度）; 未绑定组合时为空字典。

    Notes
    -----
    组合函数使用当前账户的真实上下文执行，随后再叠加账户杠杆和精度，口径与调仓一致。
    """
    account = await _get_account_or_404(session, account_id)

    portfolio_id = await get_latest_portfolio_id_by_account_id(session, account_id)
    if portfolio_id is None:
        return {}
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        return {}

    raw_target = await resolve_portfolio_target(portfolio, Context(session=session, account_id=account_id))
    return _normalize_rebalance_target(account, raw_target)


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

    running_execution_id = get_running_execution_id(account_id)
    if running_execution_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户当前没有活跃执行")

    # 先读当前状态，再发 terminate；响应码要反映“请求被受理”还是“其实已经结束”。
    current_status = await get_execution_status(running_execution_id)
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
        execution_id = await enqueue_empty_positions(account_id, algorithm=algorithm)
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

    return ExecutionTriggerResponse(
        message="已触发清仓",
        execution_id=execution_id,
        account_id=account_id,
    )
