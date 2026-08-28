"""账户级飞书执行结果通知测试路由."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel, ConfigDict

from axile.common.feishu import push_feishu_card
from axile.executor.feishu_notifications import LoggerLike, build_execute_results_feishu_card
from axile.executor.models.execution_result import ExecutionStatus
from axile.executor.models.feishu import FeishuCardConfig
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_input import UnifiedStandardInput
from axile.executor.models.unified_order import UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.server.account_assets import query_account_assets
from axile.server.api.deps import SessionDep
from axile.server.api.routes.account_support import _get_account_or_404
from axile.server.db.models import Account
from axile.server.execution.registry import clear_account_asset_refresh, try_register_account_asset_refresh

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
    """测试卡片构造所需的最小账户视图."""

    def __init__(self, account_mark: str) -> None:
        self._account_mark = account_mark
        self.logger: LoggerLike = _TestLogger()

    def _get_account_mark(self) -> str:
        return self._account_mark

    def _get_operation_display(self, order: UnifiedOrder) -> str:
        _ = order
        return "-"


class _TestLogger:
    """把测试卡片构造日志接到服务端 Loguru."""

    def info(self, message: object, *args: object, **kwargs: object) -> None:
        logger.info(str(message), *args, **kwargs)

    def error(self, message: object, *args: object, **kwargs: object) -> None:
        logger.error(str(message), *args, **kwargs)


def _test_input(account: Account, card_config: FeishuCardConfig | None) -> UnifiedStandardInput:
    """用账户公开配置构造不含交易事实的测试输入."""
    return UnifiedStandardInput.from_dict(
        {
            "channel_type": str(account.trade_channel),
            "account_config": account.account_config,
            "curr_target": {},
            "last_target": {},
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


async def _build_test_card(account: Account, card_config: FeishuCardConfig | None) -> dict[str, object]:
    """读取当前账户资产并构造测试卡片；自定义卡片不访问渠道."""
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

    output = UnifiedStandardOutput(
        account_assets=assets,
        inputs=_test_input(account, card_config),
        status=ExecutionStatus.NOOP,
        channel_type=account.trade_channel,
    )
    return build_execute_results_feishu_card(source, output, card_config)


@router.post("/{account_id}/feishu/test", response_model=AccountFeishuTestResult)
async def test_account_feishu(
    session: SessionDep,
    account_id: int,
    payload: AccountFeishuTestRequest,
) -> AccountFeishuTestResult:
    """使用账户当前资产与页面草稿测试执行结果通知卡片."""
    key = payload.feishu_key.strip()
    if not key:
        return AccountFeishuTestResult(ok=False, message="请先填写飞书机器人 key")
    account = await _get_account_or_404(session, account_id)
    card = await _build_test_card(account, payload.feishu_card_config)
    try:
        await asyncio.to_thread(push_feishu_card, card, key)
    except Exception as exc:  # noqa: BLE001 - 统一转为可展示的联通测试结果
        return AccountFeishuTestResult(ok=False, message=f"推送失败：{str(exc)[:200]}")
    return AccountFeishuTestResult(ok=True, message="测试卡片已发送，请在群内确认。")
