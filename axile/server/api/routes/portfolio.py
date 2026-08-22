"""组合的策略配置与最新权重查看相关路由."""

import asyncio
import math
import traceback
from typing import cast

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlmodel import func, select

from axile.common.config import settings
from axile.common.trade_channel import TradeChannel
from axile.domain.strategy import Strategy, WeightType
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
    PortfolioPreviewRequest,
    PortfolioPublic,
    PortfolioUpdate,
    StrategyConfig,
    StrategyConfigListPublic,
    StrategyConfigPublic,
    ValidateCustomCalcRequest,
    ValidateCustomCalcResponse,
    now_str,
)
from axile.server.repositories import (
    add_strategies_by_portfolio_id,
    get_latest_strategies_by_portfolio_id,
    get_portfolio_strategies_and_account,
    get_portfolios_every_account,
)
from axile.server.sandbox import ScriptExecutionError
from axile.server.weights import (
    DataSourceUnavailableError,
    get_latest_weights,
    get_target_balance,
    run_portfolio_calc_code,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _ensure_custom_only_when_no_data_source(*, has_strategies: bool, has_custom_code: bool) -> None:
    """
    在「仅自定义组合」模式下校验组合写入不依赖策略权重.

    未配置量化数据源（``quant_data_api`` 为空）时，只允许自定义组合：既不能携带策略列表，
    也必须提供自定义脚本；否则该组合调仓时会掉进无源可取的策略权重路径。

    Parameters
    ----------
    has_strategies : bool
        写入结果是否包含非空策略列表。
    has_custom_code : bool
        写入结果是否包含非空的 ``custom_calc_py_code``。

    Raises
    ------
    HTTPException
        无数据源且组合为策略型（含策略或缺自定义脚本）时返回 422。
    """
    if settings.quant_data_api:
        return
    if has_strategies or not has_custom_code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="未配置量化数据源，仅支持自定义组合：请填写自定义计算脚本，且不要配置策略列表。",
        )


def _require_data_source_weight_type(*, custom_code: str | None, weight_type: WeightType | None) -> None:
    """确保数据源型组合明确选择时序或截面仓位。"""
    if not custom_code and weight_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="策略组合必须选择仓位类型：ts（时序）或 cs（截面）。",
        )


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=PortfolioPublic,
)
async def create_portfolio(
    session: SessionDep,
    portfolio: PortfolioCreate,
) -> PortfolioPublic:
    """
    创建组合.

    返回完整组合信息.
    """
    _ensure_custom_only_when_no_data_source(
        has_strategies=bool(portfolio.strategies),
        has_custom_code=bool(portfolio.custom_calc_py_code),
    )
    _require_data_source_weight_type(
        custom_code=portfolio.custom_calc_py_code,
        weight_type=portfolio.weight_type,
    )
    try:
        db_portfolio = Portfolio.model_validate(portfolio)
        session.add(db_portfolio)
        # 刷出新的组合id
        await session.flush()

        # 添加组合更新记录
        new_strategies = add_strategies_by_portfolio_id(
            session,
            db_portfolio.id,
            portfolio.strategies,
            None if portfolio.custom_calc_py_code else portfolio.weight_type,
        )

        await session.commit()
        await session.refresh(db_portfolio)
    except ValueError as e:
        await session.rollback()
        logger.exception(
            f"创建组合失败: {e}",
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        await session.rollback()
        logger.exception(
            f"创建组合失败: {e}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务器错误: {str(e)}",
        )

    return PortfolioPublic(
        **db_portfolio.model_dump(),
        strategy_config=new_strategies.strategies,
        weight_type=new_strategies.weight_type,
        # 新的组合不绑定账户
        account_id=None,
    )


@router.get(
    "/",
    response_model=PortfolioListPublic,
)
async def list_portfolios(session: SessionDep) -> PortfolioListPublic:
    """获取组合列表, 不包含策略配置."""
    portfolios = (await session.execute(select(Portfolio))).scalars().all()
    return PortfolioListPublic(data=[PortfolioLitePublic.model_validate(portfolio) for portfolio in portfolios])


@router.get(
    "/{portfolio_id}",
    response_model=PortfolioPublic,
)
async def portfolio_info(session: SessionDep, portfolio_id: int) -> PortfolioPublic:
    """获取组合详情, 包含当前策略配置和当前绑定组合信息."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if not db_portfolio:
        raise HTTPException(status_code=404, detail="组合不存在")

    portfolio_id = cast("int", db_portfolio.id)
    strategy_config, weight_type, account_id = await get_portfolio_strategies_and_account(session, portfolio_id)

    return PortfolioPublic(
        **db_portfolio.model_dump(),
        strategy_config=strategy_config,
        weight_type=None if db_portfolio.custom_calc_py_code else weight_type,
        account_id=account_id,
    )


@router.delete("/{portfolio_id}")
async def delete_portfolio(session: SessionDep, portfolio_id: int) -> Message:
    """删除组合."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if not db_portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组合不存在")

    # 必须解绑相关的账户
    relevant_portfolios = await get_portfolios_every_account(session)
    for rp in relevant_portfolios.values():
        if rp == db_portfolio.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="该组合与账户关联，必须解绑才能删除组合",
            )

    # 删除组合
    await session.delete(db_portfolio)

    await session.commit()
    return Message(message="成功删除组合")


@router.patch("/{portfolio_id}", response_model=PortfolioPublic)
async def update_portfolio(session: SessionDep, portfolio_id: int, portfolio: PortfolioUpdate) -> PortfolioPublic:
    """更新组合."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if not db_portfolio:
        raise HTTPException(status_code=404, detail="组合不存在")

    # 校验更新后的结果态：不新增策略依赖，且结果仍带自定义脚本（缺自定义脚本值取现存值）。
    resulting_custom_code = (
        portfolio.custom_calc_py_code
        if "custom_calc_py_code" in portfolio.model_fields_set
        else db_portfolio.custom_calc_py_code
    )
    _ensure_custom_only_when_no_data_source(
        has_strategies=bool(portfolio.strategies),
        has_custom_code=bool(resulting_custom_code),
    )

    current_config = await get_latest_strategies_by_portfolio_id(session, portfolio_id)
    resulting_strategies = (
        portfolio.strategies
        if portfolio.strategies is not None
        else ([] if current_config is None else current_config.strategies)
    )
    resulting_weight_type = (
        portfolio.weight_type
        if "weight_type" in portfolio.model_fields_set
        else (None if current_config is None else current_config.weight_type)
    )
    _require_data_source_weight_type(
        custom_code=resulting_custom_code,
        weight_type=resulting_weight_type,
    )

    try:
        if portfolio.strategies is not None or "weight_type" in portfolio.model_fields_set:
            # 更新策略
            # 创建新策略
            add_strategies_by_portfolio_id(
                session,
                portfolio_id,
                resulting_strategies,
                None if resulting_custom_code else resulting_weight_type,
            )

            # 组合字段没有和策略配置有关，因此需要显式触发
            db_portfolio.updated_at = now_str()

        data = portfolio.model_dump(exclude_unset=True)
        data.pop("strategies", None)
        data.pop("weight_type", None)
        db_portfolio.sqlmodel_update(data)

        session.add(db_portfolio)
        await session.commit()
        await session.refresh(db_portfolio)

    except Exception as e:
        logger.exception(
            f"更新组合失败: {e}",
        )
        await session.rollback()

    strategy_config, weight_type, account_id = await get_portfolio_strategies_and_account(session, portfolio_id)

    return PortfolioPublic(
        **db_portfolio.model_dump(),
        strategy_config=strategy_config,
        weight_type=None if db_portfolio.custom_calc_py_code else weight_type,
        account_id=account_id,
    )


@router.get("/strategies_records/{portfolio_id}", response_model=StrategyConfigListPublic)
async def list_strategies_records(
    session: SessionDep, portfolio_id: int, skip: int = 0, limit: int = 100
) -> StrategyConfigListPublic:
    """获取组合策略更换记录."""
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if not db_portfolio:
        raise HTTPException(status_code=404, detail="组合不存在")

    count_statement = (
        select(func.count()).select_from(StrategyConfig).where(StrategyConfig.portfolio_id == db_portfolio.id)
    )
    count = (await session.execute(count_statement)).scalar_one()

    statement = select(StrategyConfig).where(StrategyConfig.portfolio_id == db_portfolio.id).offset(skip).limit(limit)

    records = (await session.execute(statement)).scalars().all()

    return StrategyConfigListPublic(
        data=[StrategyConfigPublic.model_validate(record) for record in records],
        count=count,
    )


async def _synthesize_target(
    strategies: list[Strategy],
    trade_channel: TradeChannel,
    weight_type: WeightType,
) -> dict[str, float]:
    """
    由一份策略配置合成目标持仓权重.

    抽出 ``latest_weights`` 与 ``preview_weights`` 的共用内核: 把策略权重与频率整理成
    ``get_latest_weights`` / ``get_target_balance`` 需要的形状, 再合成 symbol 级目标。
    不涉及任何持久化。

    Parameters
    ----------
    strategies : list[Strategy]
        策略组合 (名称 + 权重, 可选频率)。
    trade_channel : TradeChannel
        计算目标所用的交易渠道。

    Returns
    -------
    dict[str, float]
        合成后的 ``symbol -> 目标权重`` 映射。

    Raises
    ------
    HTTPException
        策略配置为空 (404); 未配置数据源 (422); 或权重服务获取失败 (500)。
    """
    strategy_config: dict[str, float] = {}
    strategy_freqs: dict[str, str] = {}
    for s in strategies:
        strategy_config[s["name"]] = s["weight"]
        base_freq = s.get("base_freq")
        if base_freq:
            strategy_freqs[s["name"]] = base_freq
    if len(strategy_config) == 0:
        raise HTTPException(status_code=404, detail="策略配置为空")

    try:
        total_df, _ = await get_latest_weights(
            strategy_config.keys(),
            weight_type=weight_type,
            strategy_freqs=strategy_freqs if strategy_freqs else None,
        )
    except DataSourceUnavailableError as e:
        # 未配置数据源属可预期的前置缺失（多为降级后的孤儿策略组合），返回 422 而非 500。
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取最新持仓权重失败, 原因: {e}",
        )

    return get_target_balance(
        dfw=total_df,
        strategy_config=strategy_config,
        trade_channel=trade_channel,
    )


async def _synthesize_custom_target(custom_calc_py_code: str) -> dict[str, float]:
    """
    执行自定义组合脚本合成目标持仓权重 (不落库).

    用于「自定义逻辑」组合的试跑与目标查看: 直接调用用户脚本里的
    ``calculate_portfolio(context)``, 而非从策略列表合成。

    Parameters
    ----------
    custom_calc_py_code : str
        组合的自定义计算脚本源码。

    Returns
    -------
    dict[str, float]
        脚本返回的 ``symbol -> 目标权重`` 映射。

    Raises
    ------
    HTTPException
        脚本执行失败时抛出 (400)。

    Notes
    -----
    此路径不绑定账户, ``context`` 传 ``None``; 依赖账户上下文
    (``context.today_return`` 等) 的脚本在试跑时取不到实时数据, 这是与真实
    调仓口径的差异。脚本在**受限子进程**中执行 (见 :mod:`axile.server.sandbox`),
    避免死循环或巨量分配拖垮承载实盘的服务进程。
    """
    result = await asyncio.to_thread(run_portfolio_calc_code, custom_calc_py_code, None)
    if not result.ok or result.target is None:
        error = result.error or ScriptExecutionError("自定义组合脚本执行失败")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"自定义组合脚本执行失败, 原因: {error}",
        )
    return result.target


async def resolve_portfolio_target(
    session: SessionDep,
    portfolio: Portfolio,
    trade_channel: TradeChannel,
) -> dict[str, float]:
    """
    解析组合当前的裸目标持仓权重 (未叠加账户杠杆与精度).

    抽出 ``portfolio_latest_weights`` 的解析内核, 供组合级权重查看与账户级目标查看
    共用: 自定义逻辑组合走脚本路径, 普通组合走策略合成路径, 分支顺序与真实调仓
    (``rebalance``) 一致。返回的是**策略净口径**权重, 账户级杠杆缩放由调用方另行叠加。

    Parameters
    ----------
    session : SessionDep
        数据库会话。
    portfolio : Portfolio
        已加载的组合对象。
    trade_channel : TradeChannel
        计算目标所用的交易渠道。

    Returns
    -------
    dict[str, float]
        ``symbol -> 目标权重`` 映射 (未含杠杆)。

    Raises
    ------
    HTTPException
        策略配置不存在 (404), 或权重服务/脚本执行失败。
    """
    # 自定义逻辑组合的目标来自用户脚本, 其策略列表天然为空; 优先走脚本路径,
    # 与真实调仓 (rebalance) 的分支顺序保持一致。
    if portfolio.custom_calc_py_code:
        return await _synthesize_custom_target(portfolio.custom_calc_py_code)

    portfolio_id = cast("int", portfolio.id)
    strategies = await get_latest_strategies_by_portfolio_id(session, portfolio_id)
    if not strategies:
        raise HTTPException(status_code=404, detail="策略配置不存在")

    if strategies.weight_type is None:
        raise HTTPException(status_code=422, detail="策略组合缺少仓位类型")
    return await _synthesize_target(strategies.strategies, trade_channel, strategies.weight_type)


@router.get(
    "/latest_weights/{portfolio_id}",
)
async def portfolio_latest_weights(
    session: SessionDep,
    portfolio_id: int,
    trade_channel: TradeChannel,
    weight_precision: float = 0.01,
    leverages: tuple[int, int] = (1, 1),
) -> dict[str, float]:
    """
    计算组合当前策略配置的持仓权重.

    通过trade_channel指定计算方式.
    """
    _ = (weight_precision, leverages)
    db_portfolio = await session.get(Portfolio, portfolio_id)
    if not db_portfolio:
        raise HTTPException(status_code=404, detail="组合不存在")

    return await resolve_portfolio_target(session, db_portfolio, trade_channel)


@router.post(
    "/preview_weights",
)
async def preview_portfolio_weights(payload: PortfolioPreviewRequest) -> dict[str, float]:
    """
    试算一份策略配置合成后的目标权重 (不落库).

    供编辑组合时的「前后对比」使用: 前端可对「旧配置」与「草稿配置」分别调用本接口,
    在同一根 bar 上背靠背取值, 从而把差异干净地归因到配置改动本身。

    Parameters
    ----------
    payload : PortfolioPreviewRequest
        待试算的策略组合与交易渠道。

    Returns
    -------
    dict[str, float]
        合成后的 ``symbol -> 目标权重`` 映射。
    """
    return await _synthesize_target(payload.strategies, payload.trade_channel, payload.weight_type)


def _ensure_weight_mapping(target: object) -> None:
    """
    轻校验自定义脚本返回值是否为合法的权重映射.

    Parameters
    ----------
    target : object
        ``calculate_portfolio`` 的返回值。

    Raises
    ------
    ValueError
        返回值不是 ``dict``、键非字符串、值非有限数字时抛出。
    """
    if not isinstance(target, dict):
        raise ValueError(f"calculate_portfolio 必须返回 dict[str, float]，实际返回 {type(target).__name__}")

    for key, value in cast("dict[object, object]", target).items():
        if not isinstance(key, str):
            raise ValueError(f"权重字典的键必须是品种字符串，实际为 {type(key).__name__}: {key!r}")
        # bool 是 int 的子类，需显式排除
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"品种 {key} 的权重必须是数字，实际为 {type(value).__name__}: {value!r}")
        if not math.isfinite(float(value)):
            raise ValueError(f"品种 {key} 的权重不是有限数值: {value!r}")


def _extract_user_code_error(exc: BaseException) -> tuple[int | None, int | None, str, str]:
    """
    从异常中提取用户代码出错位置与简洁消息.

    用户脚本经 ``exec(code, ...)`` 编译执行, 其代码对象文件名为 ``<string>``,
    因此可据此把出错行定位回用户粘贴的代码; 内部调用栈 (本服务代码、asyncio、
    线程池等) 一律忽略。

    Parameters
    ----------
    exc : BaseException
        校验过程中捕获到的异常。

    Returns
    -------
    tuple[int | None, int | None, str, str]
        ``(行号, 列偏移, 异常类型名, 简洁消息)``; 行号/列偏移无法定位时为 ``None``。
    """
    error_type = type(exc).__name__
    if isinstance(exc, SyntaxError):
        # 语法错误在编译阶段即带有精确的行列信息。
        return exc.lineno, exc.offset, error_type, exc.msg or str(exc)

    # 运行时异常: 取调用栈里最后一个 <string> 帧 (即用户脚本) 的行号。
    line: int | None = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == "<string>":
            line = frame.lineno
    return line, None, error_type, str(exc)


async def _run_custom_calc_validation(context: Context | None, custom_calc_py_code: str) -> ValidateCustomCalcResponse:
    """
    在给定上下文中执行一次自定义脚本并结构化返回结果.

    Parameters
    ----------
    context : Context | None
        传给脚本的上下文对象 (真实 ``Context`` 或样例上下文)。
    custom_calc_py_code : str
        自定义组合脚本源码。

    Returns
    -------
    ValidateCustomCalcResponse
        成功时携带目标权重; 失败时携带错误摘要与完整 traceback。

    Notes
    -----
    脚本在**受限子进程**中执行 (见 :mod:`axile.server.sandbox`), 避免死循环或巨量
    分配拖垮承载实盘的服务进程; 任何异常 (语法错误、运行时异常、返回值非法、
    超时与资源超限) 都被捕获并转为 ``valid=False`` 的结构化结果, 而非 500。

    出错行列由**子进程侧**提取后回传: 异常对象与其 traceback 无法跨进程传递,
    若只回传 ``str(exc)``, ``error_line`` / ``error_offset`` 会静默退化成 ``None``。
    """
    result = await asyncio.to_thread(run_portfolio_calc_code, custom_calc_py_code, context)

    if not result.ok or result.target is None:
        error = result.error or ScriptExecutionError("自定义组合脚本执行失败")
        return ValidateCustomCalcResponse(
            valid=False,
            error=str(error),
            traceback=error.formatted_traceback,
            error_line=error.error_line,
            error_offset=error.error_offset,
            error_type=error.error_type,
            error_message=error.error_message,
        )

    target = result.target
    try:
        _ensure_weight_mapping(target)
    except Exception as e:  # noqa: BLE001 - 校验端点需捕获返回值形状错误并原样回传
        line, offset, error_type, message = _extract_user_code_error(e)
        return ValidateCustomCalcResponse(
            valid=False,
            error=str(e),
            traceback=traceback.format_exc(),
            error_line=line,
            error_offset=offset,
            error_type=error_type,
            error_message=message,
        )

    return ValidateCustomCalcResponse(valid=True, target=target)


@router.post("/validate_custom_calc", response_model=ValidateCustomCalcResponse)
async def validate_custom_calc(session: SessionDep, payload: ValidateCustomCalcRequest) -> ValidateCustomCalcResponse:
    """
    校验自定义组合脚本 (不落库、不下单).

    执行用户脚本里的 ``calculate_portfolio(context)`` 一次并返回其目标权重或错误信息,
    供组合设置向导内联验证使用。

    - 未提供 ``account_id``: 使用样例上下文执行 (Dry-run 验证)。
    - 提供 ``account_id``: 借该账户构造真实 ``Context`` 执行 (真实账户验证), 口径与
      真实调仓一致。

    Parameters
    ----------
    session : SessionDep
        数据库会话依赖, 用于校验账户是否存在。
    payload : ValidateCustomCalcRequest
        待校验脚本源码与可选的账户标识。

    Returns
    -------
    ValidateCustomCalcResponse
        始终 HTTP 200; 以 ``valid`` 字段区分成败, 失败时携带 traceback。

    Raises
    ------
    HTTPException
        指定了不存在的 ``account_id`` 时抛出 404 (属调用错误, 非脚本错误)。
    """
    if payload.account_id is None:
        # Dry-run: 样例上下文对脚本只做属性访问, 用鸭子类型对象即可, 无需真实 Context。
        sample_context = cast("Context", build_sample_context())
        return await _run_custom_calc_validation(sample_context, payload.custom_calc_py_code)

    account = await session.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")

    # 真实账户验证: 复用真实调仓的做法, 用独立会话构造 Context, 会话在 to_thread
    # 执行期间保持打开 (Context 内部以 asyncio.run 触发自身查询)。
    async with SessionLocal() as ctx_session:
        context = Context(session=ctx_session, account_id=payload.account_id)
        return await _run_custom_calc_validation(context, payload.custom_calc_py_code)
