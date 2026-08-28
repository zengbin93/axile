"""账户级飞书执行结果通知测试路由."""

from __future__ import annotations

import asyncio
from typing import NamedTuple

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from axile.common.feishu import push_feishu_card
from axile.executor.algorithms.utils import clock_now
from axile.executor.feishu_notifications import LoggerLike, build_execute_results_feishu_card
from axile.executor.models.execution_result import AlgorithmResult, ExecutionStatus
from axile.executor.models.feishu import FeishuCardConfig
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.server.account_assets import query_account_assets
from axile.server.api.deps import SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.db.models import Account
from axile.server.execution.registry import clear_account_asset_refresh, try_register_account_asset_refresh
from axile.server.target_weight_snapshots import get_latest_account_target_snapshot

router = APIRouter()


class AccountFeishuTestRequest(BaseModel):
    """账户飞书通知测试载荷."""

    model_config = ConfigDict(extra="forbid")

    feishu_key: str
    feishu_card_config: FeishuCardConfig | None = None


class AccountFeishuTestResult(BaseModel):
    """账户飞书通知测试结果."""

    ok: bool
    message: str


class _TestNotificationSource:
    """测试卡片构造所需的最小账户视图；账户名带「样例」后缀以免与真实执行混淆。"""

    def __init__(self, account_mark: str) -> None:
        self._account_mark = account_mark
        self.logger: LoggerLike = _TestLogger()

    def _get_account_mark(self) -> str:
        return f"{self._account_mark}（样例）"

    def _get_operation_display(self, order: UnifiedOrder) -> str:
        return "买入" if order.direction == OrderDirection.BUY else "卖出"


class _TestLogger:
    """把测试卡片构造日志接到服务端 Loguru."""

    def info(self, message: object, *args: object, **kwargs: object) -> None:
        logger.info(str(message), *args, **kwargs)

    def error(self, message: object, *args: object, **kwargs: object) -> None:
        logger.error(str(message), *args, **kwargs)


def _test_input(
    account: Account,
    card_config: FeishuCardConfig | None,
    curr_target: dict[str, float],
    last_target: dict[str, float],
) -> UnifiedStandardInput:
    """用账户公开配置与样例目标构造测试输入；成交事实由样例输出承载。"""
    return UnifiedStandardInput.from_dict(
        {
            "channel_type": str(account.trade_channel),
            "account_config": account.account_config,
            "curr_target": curr_target,
            "last_target": last_target,
            "algorithm": account.algorithm,
            "trade_rules": account.trade_rules or {},
            "forbidden_symbols": account.forbidden_symbols or [],
            "risk_symbols": account.risk_symbols or [],
            "feishu_card_config": card_config.model_dump(mode="json", exclude_none=True) if card_config else None,
            "feishu_account": {
                "id": account.id,
                "name": account.name,
                "market": account.market,
                "trade_channel": str(account.trade_channel),
                "brokerage": account.brokerage,
                "remark": account.remark,
                "portfolio_id": account.portfolio_id,
                "weight_precision": account.weight_precision,
                "long_leverage": account.long_leverage,
                "short_leverage": account.short_leverage,
            },
            "extra": {
                "audit": {
                    "execution_id": None,
                    "execution_kind": "test",
                    "trigger_source": "feishu_test",
                    "is_test": True,
                }
            },
        }
    )


class _SampleLeg(NamedTuple):
    """样例成交腿：从真实持仓派生的一笔试探性调仓。"""

    symbol: str
    direction: OrderDirection
    price: float
    trade_volume: float
    target_volume: float


def _sample_legs(assets: UnifiedAccountAssets) -> list[_SampleLeg]:
    """从真实持仓取最多两个品种派生样例成交腿（首腿加仓一倍、次腿减半）。"""
    legs: list[_SampleLeg] = []
    for position in assets.positions[:2]:
        volume = float(position.volume)
        if volume <= 0:
            continue
        price = float(position.avg_price or 0.0)
        if price <= 0:
            price = float(position.market_value) / volume
        if price <= 0:
            continue
        if not legs:
            legs.append(_SampleLeg(position.symbol, OrderDirection.BUY, price, volume, volume * 2))
        else:
            half = volume / 2
            legs.append(_SampleLeg(position.symbol, OrderDirection.SELL, price, half, half))
    return legs


def _sample_symbol_results(legs: list[_SampleLeg], algorithm: str) -> dict[str, AlgorithmResult]:
    """把样例成交腿包装成品种级执行结果，字段口径与真实执行一致。"""
    trade_time = clock_now().strftime("%Y-%m-%d %H:%M:%S")
    results: dict[str, AlgorithmResult] = {}
    for index, leg in enumerate(legs):
        order_id = f"sample-order-{index + 1}"
        order = UnifiedOrder(
            order_id=order_id,
            symbol=leg.symbol,
            direction=leg.direction,
            order_type=OrderType.LIMIT,
            volume=leg.trade_volume,
            price=leg.price,
            status="FILLED",
            filled_volume=leg.trade_volume,
            avg_price=leg.price,
        )
        trade = TradeRecord(
            trade_id=f"sample-trade-{index + 1}",
            symbol=leg.symbol,
            order_id=order_id,
            trade_time=trade_time,
            trade_volume=leg.trade_volume,
            trade_price=leg.price,
            trade_value=leg.trade_volume * leg.price,
        )
        results[leg.symbol] = AlgorithmResult(
            symbol=leg.symbol,
            algorithm=algorithm,
            orders=[order],
            trades=[trade],
            target_volume=leg.target_volume,
            status=ExecutionStatus.SUCCEEDED,
        )
    return results


def _holding_weights(assets: UnifiedAccountAssets) -> dict[str, float]:
    """把当前持仓市值折算为目标权重视角的「上一期权重」。"""
    total = float(assets.total_asset)
    if total <= 0:
        return {}
    return {
        position.symbol: float(position.market_value) / total
        for position in assets.positions
        if float(position.market_value) > 0
    }


def _leg_target_weights(legs: list[_SampleLeg], assets: UnifiedAccountAssets) -> dict[str, float]:
    """无目标快照时，按样例目标市值折算当前目标权重。"""
    total = float(assets.total_asset)
    if total <= 0:
        return {}
    return {leg.symbol: leg.target_volume * leg.price / total for leg in legs}


async def _load_sample_target_weights(session: AsyncSession, account: Account) -> dict[str, float]:
    """读取账户当前组合最近的归一化目标权重作为样例目标；无快照则返回空。"""
    if account.id is None or account.portfolio_id is None:
        return {}
    snapshot = await get_latest_account_target_snapshot(session, account.id, account.portfolio_id)
    if snapshot is None or not snapshot.normalized_weights:
        return {}
    return dict(snapshot.normalized_weights)


async def _build_sample_output(
    session: AsyncSession,
    account: Account,
    assets: UnifiedAccountAssets,
    card_config: FeishuCardConfig | None,
) -> UnifiedStandardOutput:
    """用真实资产叠加样例成交，构造接近真实执行版面的输出。"""
    legs = _sample_legs(assets)
    target_weights = await _load_sample_target_weights(session, account)
    curr_target = target_weights or _leg_target_weights(legs, assets)
    algorithm = str(account.algorithm.get("method", "Unknown")) if isinstance(account.algorithm, dict) else "Unknown"
    return UnifiedStandardOutput(
        account_assets=assets,
        inputs=_test_input(account, card_config, curr_target=curr_target, last_target=_holding_weights(assets)),
        symbol_results=_sample_symbol_results(legs, algorithm),
        status=ExecutionStatus.SUCCEEDED,
        channel_type=account.trade_channel,
        execution_time=1.0,
    )


async def _build_test_card(
    session: AsyncSession,
    account: Account,
    card_config: FeishuCardConfig | None,
) -> dict[str, object]:
    """读取当前账户资产并构造样例卡片；自定义卡片不访问渠道。"""
    source = _TestNotificationSource(account.name)
    if card_config and card_config.mode == "custom":
        output = UnifiedStandardOutput(
            account_assets=UnifiedAccountAssets(available_cash=0, total_asset=0, market_value=0),
            inputs=None,
            status=ExecutionStatus.NOOP,
            channel_type=account.trade_channel,
        )
        return build_execute_results_feishu_card(source, output, card_config)

    account_id = account.id
    if account_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")
    if not try_register_account_asset_refresh(account_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账户正在执行或刷新资产，请稍后再试")
    try:
        assets = await query_account_assets(account)
    except TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="账户权益查询超时，请稍后重试") from exc
    except Exception as exc:
        logger.warning(f"账户飞书测试读取权益失败: account_id={account.id}, error={exc}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="账户权益查询失败，请检查渠道连接") from exc
    finally:
        clear_account_asset_refresh(account_id)

    output = await _build_sample_output(session, account, assets, card_config)
    return build_execute_results_feishu_card(source, output, card_config)


@router.post("/{account_id}/feishu/test", response_model=AccountFeishuTestResult)
async def test_account_feishu(
    session: SessionDep,
    account_id: int,
    payload: AccountFeishuTestRequest,
) -> AccountFeishuTestResult:
    """使用账户当前资产、目标快照与页面草稿推送样例执行结果卡片。"""
    key = payload.feishu_key.strip()
    if not key:
        return AccountFeishuTestResult(ok=False, message="请先填写飞书机器人 key")
    account = await _get_account_or_404(session, account_id)
    card = await _build_test_card(session, account, payload.feishu_card_config)
    try:
        await asyncio.to_thread(push_feishu_card, card, key)
    except Exception as exc:  # noqa: BLE001 - 统一转为可展示的联通测试结果
        return AccountFeishuTestResult(ok=False, message=f"推送失败：{str(exc)[:200]}")
    return AccountFeishuTestResult(ok=True, message="样例卡片已发送，请在群内确认。")
