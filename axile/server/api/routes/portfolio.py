"""自定义函数投资组合路由."""

import asyncio
import math
import traceback
from typing import cast

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlmodel import select

from axile.server.api.deps import SessionDep
from axile.server.context import Context, build_sample_context
from axile.server.core.db import SessionLocal
from axile.server.db.models import (
    Account,
    Message,
    Portfolio,
    PortfolioCreate,
    PortfolioListPublic,
    PortfolioLitePublic,
    PortfolioPublic,
    PortfolioUpdate,
    TargetWeightSnapshotPublic,
    ValidateCustomCalcRequest,
    ValidateCustomCalcResponse,
)
from axile.server.execution.rebalance import _normalize_rebalance_target
from axile.server.portfolio_targets import calculate_portfolio_target
from axile.server.repositories import get_latest_account_id_by_portfolio_id, get_portfolios_every_account
from axile.server.sandbox import ScriptExecutionError
from axile.server.target_weight_snapshots import (
    append_target_weight_snapshot,
    get_latest_portfolio_target_snapshot,
    target_snapshot_public,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _portfolio_public(session: SessionDep, portfolio: Portfolio) -> PortfolioPublic:
    """构造带当前绑定账户的组合公开响应."""
    portfolio_id = cast("int", portfolio.id)
    account_id = await get_latest_account_id_by_portfolio_id(session, portfolio_id)
    return PortfolioPublic(**portfolio.model_dump(), account_id=account_id)


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=PortfolioPublic)
async def create_portfolio(session: SessionDep, portfolio: PortfolioCreate) -> PortfolioPublic:
    """创建一个由自定义函数计算目标权重的组合."""
    try:
        db_portfolio = Portfolio.model_validate(portfolio)
        session.add(db_portfolio)
        await session.commit()
        await session.refresh(db_portfolio)
    except Exception as exc:
        await session.rollback()
        logger.exception("创建组合失败: {}", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"服务器错误: {exc}") from exc
    return PortfolioPublic(**db_portfolio.model_dump(), account_id=None)


@router.get("/", response_model=PortfolioListPublic)
async def list_portfolios(session: SessionDep) -> PortfolioListPublic:
    """获取组合列表."""
    portfolios = (await session.execute(select(Portfolio))).scalars().all()
    return PortfolioListPublic(data=[PortfolioLitePublic.model_validate(portfolio) for portfolio in portfolios])


@router.get("/{portfolio_id:int}", response_model=PortfolioPublic)
async def portfolio_info(session: SessionDep, portfolio_id: int) -> PortfolioPublic:
    """获取组合详情和当前绑定账户."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if db_portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")
    return await _portfolio_public(session, db_portfolio)


@router.delete("/{portfolio_id:int}")
async def delete_portfolio(session: SessionDep, portfolio_id: int) -> Message:
    """删除未绑定账户的组合."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if db_portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")

    if portfolio_id in (await get_portfolios_every_account(session)).values():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="该组合与账户关联，必须解绑才能删除组合",
        )

    await session.delete(db_portfolio)
    await session.commit()
    return Message(message="成功删除组合")


@router.patch("/{portfolio_id:int}", response_model=PortfolioPublic)
async def update_portfolio(session: SessionDep, portfolio_id: int, portfolio: PortfolioUpdate) -> PortfolioPublic:
    """局部更新组合；自定义函数不可清空."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if db_portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")

    try:
        db_portfolio.sqlmodel_update(portfolio.model_dump(exclude_unset=True))
        session.add(db_portfolio)
        await session.commit()
        await session.refresh(db_portfolio)
    except Exception as exc:
        await session.rollback()
        logger.exception("更新组合失败: {}", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"服务器错误: {exc}") from exc
    return await _portfolio_public(session, db_portfolio)


def _ensure_weight_mapping(target: object) -> None:
    """校验组合函数返回 ``symbol -> finite weight`` 映射."""
    if not isinstance(target, dict):
        raise ValueError(f"calculate_portfolio 必须返回 dict[str, float]，实际返回 {type(target).__name__}")
    for key, value in cast("dict[object, object]", target).items():
        if not isinstance(key, str):
            raise ValueError(f"权重字典的键必须是品种字符串，实际为 {type(key).__name__}: {key!r}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"品种 {key} 的权重必须是数字，实际为 {type(value).__name__}: {value!r}")
        if not math.isfinite(float(value)):
            raise ValueError(f"品种 {key} 的权重不是有限数值: {value!r}")


async def resolve_portfolio_target(portfolio: Portfolio, context: object) -> dict[str, float]:
    """执行组合函数并返回未经账户杠杆和精度处理的目标权重."""
    result = await asyncio.to_thread(calculate_portfolio_target, portfolio.custom_calc_py_code, context)
    if not result.ok or result.target is None:
        error = result.error or ScriptExecutionError("自定义组合函数执行失败")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"自定义组合函数执行失败, 原因: {error}",
        )
    _ensure_weight_mapping(result.target)
    return result.target


@router.get("/latest_weights/{portfolio_id}")
async def portfolio_latest_weights(session: SessionDep, portfolio_id: int) -> dict[str, float]:
    """兼容接口：只读组合最近成功计算的原始权重."""
    if await session.get(Portfolio, portfolio_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")
    snapshot = await get_latest_portfolio_target_snapshot(session, portfolio_id)
    return snapshot.raw_weights if snapshot and snapshot.raw_weights is not None else {}


@router.get("/{portfolio_id:int}/target_snapshot", response_model=TargetWeightSnapshotPublic)
async def portfolio_target_snapshot(session: SessionDep, portfolio_id: int) -> TargetWeightSnapshotPublic:
    """只读组合最近成功计算的原始目标快照."""
    if await session.get(Portfolio, portfolio_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")
    snapshot = await get_latest_portfolio_target_snapshot(session, portfolio_id)
    return target_snapshot_public(snapshot, weight_kind="raw")


@router.post("/{portfolio_id:int}/target_snapshot/refresh", response_model=TargetWeightSnapshotPublic)
async def refresh_portfolio_target_snapshot(session: SessionDep, portfolio_id: int) -> TargetWeightSnapshotPublic:
    """按用户请求执行一次组合函数并持久化当前目标."""
    portfolio = await session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")

    account_id = await get_latest_account_id_by_portfolio_id(session, portfolio_id)
    if account_id is None:
        raw_target = await resolve_portfolio_target(portfolio, build_sample_context())
        normalized_target = None
    else:
        account = await session.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="绑定账户不存在")
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
    return target_snapshot_public(snapshot, weight_kind="raw")


def _extract_user_code_error(exc: BaseException) -> tuple[int | None, int | None, str, str]:
    """从异常中提取用户代码行列和错误摘要."""
    error_type = type(exc).__name__
    if isinstance(exc, SyntaxError):
        return exc.lineno, exc.offset, error_type, exc.msg or str(exc)
    line: int | None = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == "<string>":
            line = frame.lineno
    return line, None, error_type, str(exc)


async def _run_custom_calc_validation(context: object, custom_calc_py_code: str) -> ValidateCustomCalcResponse:
    """在给定上下文中试跑自定义组合函数并返回结构化结果."""
    result = await asyncio.to_thread(calculate_portfolio_target, custom_calc_py_code, context)
    if not result.ok or result.target is None:
        error = result.error or ScriptExecutionError("自定义组合函数执行失败")
        return ValidateCustomCalcResponse(
            valid=False,
            error=str(error),
            traceback=error.formatted_traceback,
            error_line=error.error_line,
            error_offset=error.error_offset,
            error_type=error.error_type,
            error_message=error.error_message,
        )

    try:
        _ensure_weight_mapping(result.target)
    except Exception as exc:
        line, offset, error_type, message = _extract_user_code_error(exc)
        return ValidateCustomCalcResponse(
            valid=False,
            error=str(exc),
            traceback=traceback.format_exc(),
            error_line=line,
            error_offset=offset,
            error_type=error_type,
            error_message=message,
        )
    return ValidateCustomCalcResponse(valid=True, target=result.target)


@router.post("/validate_custom_calc", response_model=ValidateCustomCalcResponse)
async def validate_custom_calc(session: SessionDep, payload: ValidateCustomCalcRequest) -> ValidateCustomCalcResponse:
    """使用样例或真实账户上下文试跑自定义组合函数."""
    if payload.account_id is None:
        return await _run_custom_calc_validation(build_sample_context(), payload.custom_calc_py_code)

    if await session.get(Account, payload.account_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")

    async with SessionLocal() as context_session:
        context = Context(session=context_session, account_id=payload.account_id)
        return await _run_custom_calc_validation(context, payload.custom_calc_py_code)
