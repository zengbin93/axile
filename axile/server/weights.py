"""策略权重加载与调仓目标计算辅助函数."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import cast

import aiohttp
import loguru
import pandas as pd
from tenacity import (
    after_log,
    before_log,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from axile.channels import get_channel
from axile.common.config import settings
from axile.common.trade_channel import TradeChannel
from axile.server.context import Context
from axile.server.sandbox import ScriptExecutionError, ScriptResult, run_portfolio_script, snapshot_context

standard_logger = logging.getLogger(__name__)


class StaleDataError(Exception):
    """权重数据过时异常."""

    def __init__(self, strategy: str, update_time: str, freq: str, age_seconds: float) -> None:
        self.strategy = strategy
        self.update_time = update_time
        self.freq = freq
        self.age_seconds = age_seconds
        super().__init__(f"策略 {strategy} 数据过时: update_time={update_time}, 频率={freq}, 已过 {age_seconds:.0f} 秒")


class DataSourceUnavailableError(Exception):
    """未配置量化数据源时请求策略权重的异常.

    Notes
    -----
    「仅自定义组合」模式下 ``quant_data_api`` 为空，策略权重路径无源可取。此异常作为
    :func:`get_latest_weights` 的入口护栏抛出，统一兜住执行调仓与组合查看/试算两条路径，
    以及「配过数据源后又清空」导致的孤儿策略组合。
    """

    def __init__(self) -> None:
        super().__init__("未配置量化数据源（quant_data_api 为空），仅支持自定义组合；策略权重不可用。")


def parse_freq(freq: str) -> int:
    """
    将频率字符串转换为秒数.

    Parameters
    ----------
    freq : str
        频率字符串，例如 ``15m``、``1h`` 或 ``1d``。

    Returns
    -------
    int
        解析后的秒数。

    Raises
    ------
    ValueError
        当频率字符串为空或格式不受支持时抛出。
    """
    freq = freq.strip().lower()
    if not freq:
        raise ValueError("频率字符串不能为空")

    unit_map = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }

    import re

    match = re.match(r"^(\d+)([smhdw])$", freq)
    if match is None:
        raise ValueError(f"无法解析的频率格式: {freq}，支持格式如 15m, 1h, 1d")

    value = int(match.group(1))
    unit = match.group(2)
    return value * unit_map[unit]


def run_portfolio_calc_code(py_portfolio_code: str, context: Context | None = None) -> ScriptResult:
    """
    在受限子进程中执行自定义投资组合计算代码.

    Parameters
    ----------
    py_portfolio_code : str
        自定义组合脚本源码。
    context : Context | None, optional
        传给 ``calculate_portfolio(context)`` 的上下文对象。

    Returns
    -------
    ScriptResult
        统一的执行结果；失败时 ``error`` 携带结构化错误（含用户脚本出错行列）。

    Notes
    -----
    ``context`` 持有数据库会话，无法跨进程传递，因此先由
    :func:`axile.server.sandbox.snapshot_context` 拍成纯标量快照再送进子进程；
    快照对脚本呈现的属性访问行为与原 ``Context`` 一致。

    该函数返回中性结果对象而不抛异常：三个调用方各有不同的错误契约，由各自
    映射（见 :func:`axile.server.sandbox.run_portfolio_script` 的 Notes）。
    """
    return run_portfolio_script(py_portfolio_code, snapshot_context(context))


def invoke_portfolio_calc_code(py_portfolio_code: str, context: Context | None = None) -> dict[str, float]:
    """
    执行自定义投资组合计算代码并返回目标权重.

    Parameters
    ----------
    py_portfolio_code : str
        自定义组合脚本源码。
    context : Context | None, optional
        传给 ``calculate_portfolio(context)`` 的上下文对象。

    Returns
    -------
    dict[str, float]
        计算得到的品种目标权重映射。

    Raises
    ------
    ScriptExecutionError
        脚本执行失败（含语法错误、运行时异常、超时与资源超限）时抛出。

    Notes
    -----
    脚本自 issue #29 起在**独立子进程**中执行并受资源上限约束，不再于服务进程内
    直接 ``exec``。保留本函数是为了给「只关心权重、失败即抛」的调用方一个薄封装。
    """
    result = run_portfolio_calc_code(py_portfolio_code, context)
    if not result.ok or result.target is None:
        raise result.error or ScriptExecutionError("自定义组合脚本执行失败")
    return result.target


def get_target_balance(
    dfw: pd.DataFrame,
    strategy_config: dict[str, float],
    trade_channel: TradeChannel,
) -> dict[str, float]:
    """
    根据策略权重计算聚合后的目标仓位.

    Parameters
    ----------
    dfw : pd.DataFrame
        已按策略过滤后的最新持仓权重数据。
    strategy_config : dict[str, float]
        策略名称到组合权重的映射。
    trade_channel : TradeChannel
        当前实盘渠道，用于应用渠道特定的目标权重计算规则。

    Returns
    -------
    dict[str, float]
        聚合后的品种目标权重。
    """
    weighted_df = get_channel(trade_channel).target_transform(strategy_config, dfw)
    curr_target: pd.DataFrame = (
        weighted_df[["symbol", "contribution"]].groupby("symbol", as_index=False).sum()  # type: ignore[assignment]
    )
    return cast("dict[str, float]", curr_target.set_index("symbol")["contribution"].to_dict())


async def _fetch_latest_weights_frame(url: str) -> pd.DataFrame:
    """从标准权重接口拉取完整权重数据表."""
    req_params = {
        "api_name": "get_latest_weights",
        "token": settings.quant_data_token,
        "params": {"v": 2, "ttl": 0},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=req_params) as res:
            result = await res.json()
            return pd.DataFrame(result["data"]["items"])


def _validate_strategy_freshness(
    *,
    df_filtered: pd.DataFrame,
    strategy_freqs: dict[str, str],
    logger: "loguru.Logger",
) -> None:
    """校验目标策略的权重数据是否超过允许时效."""
    now = datetime.now()
    for strategy_name, freq in strategy_freqs.items():
        strategy_data = df_filtered[df_filtered["strategy"] == strategy_name]
        if strategy_data.empty:
            continue

        update_time_str = str(strategy_data["update_time"].iloc[0])
        update_time = pd.to_datetime(update_time_str)
        age_seconds = float((now - update_time).total_seconds())
        freq_seconds = parse_freq(freq)
        if age_seconds > freq_seconds:
            logger.error(
                f"策略 {strategy_name} 数据过时: "
                f"update_time={update_time_str}, 频率={freq}, "
                f"已过 {age_seconds:.0f} 秒 > {freq_seconds} 秒"
            )
            raise StaleDataError(
                strategy=strategy_name,
                update_time=update_time_str,
                freq=freq,
                age_seconds=age_seconds,
            )

        logger.debug(f"策略 {strategy_name} 数据新鲜: 已过 {age_seconds:.0f} 秒 <= {freq_seconds} 秒")


def _extract_target_update_time(filtered_df: pd.DataFrame) -> str | None:
    """
    提取目标权重数据中最旧的 ``update_time``.

    Parameters
    ----------
    filtered_df : pd.DataFrame
        已按目标策略过滤、仍保留 ``update_time`` 列的权重数据表。

    Returns
    -------
    str | None
        参与本次计算的策略里最旧的 ``update_time``（ISO8601 字符串），
        代表本次目标数据时效的上界；无有效时间时返回 ``None``。

    Notes
    -----
    多策略各自 ``update_time`` 可能不同，取最旧值以反映最差数据新鲜度，
    供审计与前端展示「目标是基于多久前的数据算出的」。
    """
    if "update_time" not in filtered_df.columns or filtered_df.empty:
        return None
    times = pd.to_datetime(filtered_df["update_time"], errors="coerce").dropna()
    if times.empty:
        return None
    # 用 Python 的 min 而非 pandas 的 .min() 归约：后者在 numpy 被重复 import
    # 的环境（如覆盖率插桩）下会触发 no_default 哨兵类型错误。
    return min(times.tolist()).isoformat()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    # 数据源缺失是配置态、重试也不会变，快速失败；仅对网络/解析等瞬时错误重试。
    retry=retry_if_not_exception_type(DataSourceUnavailableError),
    before=before_log(standard_logger, logging.INFO),
    after=after_log(standard_logger, logging.WARN),
    reraise=True,
)
async def get_latest_weights(
    strategies: Iterable[str],
    logger: "loguru.Logger" = loguru.logger,
    strategy_freqs: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """
    从权重服务异步加载目标策略的最新权重.

    Parameters
    ----------
    strategies : Iterable[str]
        需要查询的策略名称列表。
    logger : loguru.Logger, optional
        用于记录加载过程的 logger。
    strategy_freqs : dict[str, str] | None, optional
        策略频率配置；提供时会额外校验数据时效。

    Returns
    -------
    tuple[pd.DataFrame, str | None]
        二元组：仅保留 ``strategy``、``symbol``、``weight`` 列的权重表，
        以及参与计算策略里最旧的 ``update_time``（ISO8601 字符串，无有效时间时为 ``None``）。

    Raises
    ------
    DataSourceUnavailableError
        当未配置量化数据源（``quant_data_api`` 为空）时抛出——「仅自定义组合」模式下
        策略权重无源可取。
    StaleDataError
        当任一策略数据超过其频率时效时抛出。
    """
    url = settings.quant_data_api
    if not url:
        raise DataSourceUnavailableError
    strategy_list = list(strategies)
    full_df = await _fetch_latest_weights_frame(url)

    available_strategies = set(full_df["strategy"].unique())
    target_strategies = set(strategy_list)
    missing_strategies = target_strategies - available_strategies
    if missing_strategies:
        logger.warning(f"以下策略不在获取的数据中: {list(missing_strategies)}")

    filtered_df = full_df.loc[full_df["strategy"].isin(strategy_list)]
    if strategy_freqs:
        _validate_strategy_freshness(
            df_filtered=filtered_df,
            strategy_freqs=strategy_freqs,
            logger=logger,
        )

    target_update_time = _extract_target_update_time(filtered_df)
    result_df: pd.DataFrame = filtered_df.loc[:, ["strategy", "symbol", "weight"]]
    logger.info(
        f"权重数据加载完成: source={url}, strategies={len(strategy_list)}, "
        f"missing={len(missing_strategies)}, total_rows={len(full_df)}, matched_rows={len(result_df)}"
    )
    return result_df, target_update_time
