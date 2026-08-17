"""CTP 期货交易执行器实现.

本模块定义 `CTPExecutor`，负责封装 CTP 渠道的连接、下单、查询、回调与
统一执行器接口适配；不再提供模块级的 `execute()` / `empty_positions()` 包装入口。
"""

from datetime import datetime
from typing import Any, override

import czsc  # pyright: ignore[reportMissingTypeStubs]
import loguru

from axile.common.trade_channel import TradeChannel
from axile.executor.abstract_executor.base import AbstractExecutor
from axile.executor.account_control.guard import AccountControlGuard
from axile.executor.ctp.core.market_data import CtpMarketData
from axile.executor.ctp.core.objects import DirectionType, OffsetFlagType, OrderPriceType, OrderStatusType
from axile.executor.ctp.core.option_action import (
    OptionActionRecord,
    OptionActionStatus,
    OptionActionType,
)
from axile.executor.ctp.core.trader import CtpTrader

# 导入 CTP 专用组件
from axile.executor.ctp.utils.data_converter import get_account_assets
from axile.executor.ctp.utils.instrument_kind import is_option, is_option_call
from axile.executor.ctp.utils.main_contracts import format_symbol
from axile.executor.ctp.utils.market_data_helpers import get_first_tickers
from axile.executor.ctp.utils.position_manager import account_login
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_callback import (
    OrderUpdateCallback,
    PriceDataCallback,
    TradeRecordCallback,
    UnifiedCallbackClient,
)
from axile.executor.models.unified_input import AccountConfig, CTPAccountConfig, UnifiedStandardInput
from axile.executor.models.unified_order import OrderDirection, OrderType, TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput
from axile.executor.models.unified_price import UnifiedPriceData

logger = loguru.logger


class CTPExecutor(AbstractExecutor, UnifiedCallbackClient):
    """
    CTP期货交易执行器.

    实现 UnifiedCallbackClient 接口，支持订单更新和成交记录的回调。
    """

    def __init__(self, channel_type: TradeChannel, account_config: AccountConfig | None = None) -> None:
        """
        初始化 CTP 交易执行器.

        Parameters
        ----------
        channel_type : TradeChannel
            交易渠道类型；对于 CTP 应传入 ``TradeChannel.CTP``。
        account_config : AccountConfig | None, optional
            CTP 账户配置信息，包含 ``broker_id``、``investor_id`` 等字段。
        """
        # CTP特定组件 - 必须在调用 super().__init__() 之前初始化
        # 因为 super().__init__() 会调用 _initialize_connection()
        self.trader: CtpTrader | None = None
        self.md_client: CtpMarketData | None = None

        # 执行时间记录，用于过滤本次执行的订单
        self.execution_start_time: datetime | None = None

        # 调用父类初始化（会触发 _initialize_connection）
        super().__init__(channel_type, account_config)

        logger.info(f"[{self.channel_type.value}] CTPAbstractExecutor 初始化完成")

    @override
    def set_account_control_guard(self, guard: AccountControlGuard | None) -> None:
        """同步为 executor 与底层 trader 绑定账户控制 guard."""
        super().set_account_control_guard(guard)
        if self.trader is not None:
            self.trader.set_account_control_guard(guard)

    # ==================== 连接管理方法 ====================

    @override
    def _initialize_connection(self, account_config: AccountConfig) -> None:
        """
        初始化并建立CTP连接.

        使用现有的account_login工具函数，初始化交易和行情连接。

        Parameters
        ----------
        account_config : AccountConfig
            CTP 账户配置信息。
        """
        try:
            logger.info(f"[{self.channel_type.value}] 开始初始化CTP连接")

            # 验证账户配置类型
            if not isinstance(account_config, CTPAccountConfig):
                raise TypeError(f"CTPExecutor requires CTPAccountConfig, got {type(account_config).__name__}")

            # 使用现有工具函数登录并初始化交易客户端
            self.trader = account_login(account_config, self.logger)

            # 查询合约信息
            _ = self.trader.query_instruments()

            # 初始化行情客户端
            md_front = getattr(account_config, "md_front", None)
            if not md_front:
                raise ValueError("md_front is required for CTP market data connection")
            self.md_client = CtpMarketData(
                md_front,
                account_id=f"{account_config.broker_id}_{account_config.investor_id}",
            )
            self.md_client.connect()
            self._register_execution_query_runtime_callback_observers()

            logger.info(f"[{self.channel_type.value}] CTP连接初始化成功")

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] CTP连接初始化失败: {e}")
            raise ConnectionError(f"CTP连接初始化失败: {e}")

    @override
    def _verify_connection(self) -> bool:
        """
        验证CTP连接是否有效.

        检查交易客户端和行情客户端的连接状态。

        Returns
        -------
        bool
            连接有效时返回 ``True``，否则返回 ``False``。
        """
        try:
            if not self.trader or not self.md_client:
                return False

            # 检查交易客户端状态
            if not self.trader.connected:
                return False

            # 检查行情客户端状态
            if not self.md_client.connected:
                return False

            return True

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 连接验证失败: {e}")
            return False

    # ==================== 核心交易方法 ====================

    @override
    def _check_trading_time(self) -> bool:
        """
        检查是否在交易日.

        CTP期货交易时间检查在具体下单时进行，
        这里只检查是否是交易日。

        Returns
        -------
        bool
            当前为交易日时返回 ``True``，否则返回 ``False``。
        """
        try:
            # 检查是否是交易日
            is_trading_date = czsc.is_trading_date()
            if not is_trading_date:
                logger.info(f"[{self.channel_type.value}] 当前不是交易日")
                return False

            # 是交易日，允许继续执行
            # 具体品种的交易时间检查会在下单时进行
            return True

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 检查交易日失败: {e}")
            # 出错时默认允许交易
            return True

    @override
    def get_account_assets(self) -> UnifiedAccountAssets:
        """
        获取CTP账户资产.

        使用现有的get_account_assets工具函数获取账户资产信息，
        转换为UnifiedAccountAssets格式，保留CTP特定持仓详情。

        Returns
        -------
        UnifiedAccountAssets
            统一格式的账户资产信息。
        """
        try:
            if not self.trader or not self.md_client:
                raise RuntimeError("CTP连接未建立")

            # 使用现有工具函数获取账户资产
            account_assets_data = get_account_assets(self.trader, self.md_client, self.logger)

            # 转换为UnifiedAccountAssets，保留CTP特定数据在extra字段
            unified_assets = UnifiedAccountAssets.create(
                available_cash=account_assets_data["available_cash"],
                total_asset=account_assets_data["total_asset"],
                positions_data=account_assets_data["positions"],
                channel_type=self.channel_type,
            )

            logger.info(f"[{self.channel_type.value}] 账户资产获取完成 - 总资产: {unified_assets.total_asset}")
            return unified_assets

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 获取账户资产失败: {e}")
            raise

    @override
    def get_market_data(self, symbols: list[str]) -> dict[str, UnifiedPriceData]:
        """
        获取CTP市场数据.

        使用现有的get_first_tickers工具函数获取行情数据，
        转换为UnifiedPriceData格式。

        Parameters
        ----------
        symbols : list[str]
            需要获取行情的品种代码列表。

        Returns
        -------
        dict[str, UnifiedPriceData]
            品种代码到市场数据的映射字典。
        """
        try:
            if not self.trader or not self.md_client:
                raise RuntimeError("CTP连接未建立")

            # 使用现有工具函数获取行情数据
            market_data_dict = get_first_tickers(self.trader, self.md_client, symbols, self.logger)

            # get_first_tickers已经返回UnifiedPriceData格式，直接使用
            logger.info(f"[{self.channel_type.value}] 市场数据获取完成 - {len(market_data_dict)}个品种")
            return market_data_dict

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 获取市场数据失败: {e}")
            raise

    # ==================== 订单管理方法 ====================

    @override
    def _place_order_impl(
        self,
        symbol: str,
        direction: OrderDirection,
        order_type: OrderType,
        volume: float,
        price: float = 0,
        **kwargs: Any,
    ) -> UnifiedOrder:
        """
        CTP下单，支持offset flag等CTP特定参数.

        从**kwargs中提取CTP特定参数如offset_flag，转换为CTP订单并提交。

        Parameters
        ----------
        symbol : str
            品种代码。
        direction : OrderDirection
            交易方向。
        order_type : OrderType
            订单类型，支持 ``MARKET`` 和 ``LIMIT``。
        volume : float
            交易数量。
        price : float, default=0
            下单价格，仅限价单使用。
        **kwargs : Any
            CTP 特定参数，例如 ``offset_flag`` 开平标志。

        Returns
        -------
        UnifiedOrder
            统一格式的订单对象。
        """
        try:
            if not self.trader:
                raise RuntimeError("CTP交易客户端未连接")

            # 转换交易方向
            ctp_direction = DirectionType.BUY if direction == OrderDirection.BUY else DirectionType.SELL

            # 转换订单类型
            ctp_price_type = OrderPriceType.LIMIT_PRICE if order_type == OrderType.LIMIT else OrderPriceType.ANY_PRICE

            # 提取CTP特定参数
            offset_flag = kwargs.get("offset_flag", OffsetFlagType.OPEN)
            if isinstance(offset_flag, str):
                offset_flag = OffsetFlagType(offset_flag)

            # 提取 trade_rule（可选）：算法层可通过 kwargs 传入，
            # 让 CTP 风控模块在期权卖方等场景下读取 ``margin_ratio`` 兜底。
            trade_rule_raw = kwargs.get("trade_rule")
            trade_rule: dict[str, object] | None = trade_rule_raw if isinstance(trade_rule_raw, dict) else None

            # 确定下单价格（市价单时使用合理价格）
            if order_type == OrderType.MARKET:
                price = 0  # CTP市价单价格设为0

            # 调用CTP交易客户端下单
            # CTP 期货手数必须为整数
            order_ref: str = self.trader.insert_order(
                instrument_id=symbol,
                direction=ctp_direction,
                offset=offset_flag,
                price_type=ctp_price_type,
                limit_price=price,
                volume=int(volume),
                trade_rule=trade_rule,
            )

            # 获取创建的UnifiedOrder
            unified_order = self.trader.get_unified_order(order_ref)
            if not unified_order:
                raise RuntimeError(f"下单成功但无法获取订单信息: {order_ref}")

            price_str = f"@{price}" if price > 0 else "@MARKET"
            logger.info(
                f"[{self.channel_type.value}] 下单成功 - {symbol} {direction.value} "
                f"{volume}手{price_str} offset={offset_flag.value}"
            )

            return unified_order

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 下单失败 - {symbol} {direction.value} {volume}手: {e}")
            raise

    @override
    def _get_pending_orders_impl(self, symbol: str | None = None) -> list[UnifiedOrder]:
        """
        获取 CTP 未完成订单.

        查询所有未成交的订单，转换为UnifiedOrder列表。

        Returns
        -------
            list[UnifiedOrder]: 未完成订单列表
        """
        try:
            if not self.trader:
                raise RuntimeError("CTP交易客户端未连接")

            # 获取所有订单（已经是UnifiedOrder格式）
            all_orders: list[UnifiedOrder] = self.trader.get_unified_orders()

            # 过滤未完成订单
            pending_orders: list[UnifiedOrder] = []
            for unified_order in all_orders:
                # 由于已经得到UnifiedOrder，需要检查原始状态
                ctp_info = unified_order.extra or {}
                ctp_status = ctp_info.get("status", "")

                if symbol is not None and unified_order.symbol != symbol:
                    continue

                if ctp_status in [
                    OrderStatusType.NO_TRADE_QUEUEING,
                    OrderStatusType.NOT_TOUCHED,
                ]:
                    pending_orders.append(unified_order)

            logger.info(f"[{self.channel_type.value}] 获取到{len(pending_orders)}个未完成订单")
            return pending_orders

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 获取未完成订单失败: {e}")
            raise

    @override
    def _get_execution_pending_orders_snapshot_fetcher(self):
        """返回 Execution 内部共享的 CTP 本地挂单快照，不额外记远端查询额度."""
        return lambda: self._get_pending_orders_impl(None)

    @override
    def get_tick_size(self, symbol: str) -> float | None:
        """
        获取CTP合约的最小价格变动单位.

        从合约信息中获取 PriceTick（最小变动价位）。

        Parameters
        ----------
        symbol : str
            合约代码。

        Returns
        -------
        float | None
            最小价格变动单位；如果合约不存在或未查询到则返回 ``None``。
        """
        try:
            if not self.trader:
                return None

            if symbol in self.trader.instruments:
                tick_size = self.trader.instruments[symbol].PriceTick
                if tick_size and tick_size > 0:
                    return tick_size

            return None

        except Exception as e:
            logger.warning(f"[{self.channel_type.value}] 获取 {symbol} tick_size 失败: {e}")
            return None

    @override
    def _cleanup(self) -> None:
        """
        清理CTP资源.

        执行级别清理（每次 execute 结束都会调用）。

        Notes
        -----
        CTP 的交易与行情连接在 ``__init__`` 时建立，推荐在 ``stop()`` 中统一关闭。
        """
        try:
            if self.md_client:
                self.md_client.request_stop()
                self.md_client.close()

            if self.trader:
                self.trader.request_stop()
                self.trader.close()

            logger.info(f"[{self.channel_type.value}] 资源清理完成（执行级）")

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 资源清理失败: {e}")

    @override
    def _get_account_mark(self) -> str:
        """
        获取CTP账户标识.

        从账户配置中提取账户标识，用于飞书通知。

        Returns
        -------
        str
            账户标识字符串。
        """
        try:
            if not self.account_config:
                return f"{self.channel_type.value}_unknown"

            investor_id = getattr(self.account_config, "investor_id", "unknown")
            broker_id = getattr(self.account_config, "broker_id", "unknown")

            return f"{self.channel_type.value}_{broker_id}_{investor_id}"

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 获取账户标识失败: {e}")
            return f"{self.channel_type.value}_error"

    @override
    def _get_default_trade_rules_for_empty(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """
        获取CTP清仓时的默认交易规则.

        为没有指定交易规则的品种提供默认的清仓规则。

        Parameters
        ----------
        symbols : list[str]
            需要清仓的品种代码列表。

        Returns
        -------
        dict[str, dict[str, Any]]
            默认的交易规则字典。
        """
        default_rules: dict[str, dict[str, Any]] = {}

        for symbol in symbols:
            default_rules[symbol] = {
                "price": "PASSIVE",  # 默认使用被动价格
                "offset_priority": "今昨,开",  # 默认平仓优先级
                "max_single_order_size": 50,  # 默认单笔最大下单量
            }

        logger.info(f"[{self.channel_type.value}] 生成{len(default_rules)}个品种的默认交易规则")
        return default_rules

    @override
    def _get_default_algorithm(self) -> dict[str, Any]:
        """获取 CTP 清仓路径的默认算法配置."""
        return {"method": "TARGET-POS-TASK", "params": {}}

    @override
    def execute(
        self,
        standard_input: UnifiedStandardInput,
        cleanup: bool = True,
        retain_runtime: bool = False,
    ) -> UnifiedStandardOutput:
        """
        重写execute方法，添加执行时间记录.

        Parameters
        ----------
        standard_input : UnifiedStandardInput
            统一的标准输入参数。
        cleanup : bool, default=True
            是否在执行完成后清理资源；设为 ``False`` 时可保持连接以支持长期运行或间隔执行。
        retain_runtime : bool, default=False
            是否在返回后保留当前 execution runtime。

        Returns
        -------
        UnifiedStandardOutput
            统一的标准输出结果。
        """
        if not isinstance(standard_input, UnifiedStandardInput):
            raise TypeError("standard_input 必须是 UnifiedStandardInput")

        # CTP 在进入统一编排前要先做一次“输入归一化”：
        # 1. 把外部传入的符号统一成内部可交易形式；
        # 2. 为账户已有持仓但未显式出现在输入中的合约补 0 target，
        #    这样统一编排层才能感知“需要平老仓”的 symbol。
        standard_input = self._normalize_standard_input_symbols(standard_input)

        # 记录执行开始时间，用于过滤本次执行的订单
        self.execution_start_time = datetime.now()

        # 获取算法名称
        algorithm_method = standard_input.algorithm.get("method", "Unknown")

        logger.info(f"[{self.channel_type.value}] 开始执行交易 - 算法: {algorithm_method}")

        # 调用父类的execute方法（传递 cleanup 参数）
        result = super().execute(standard_input, cleanup=cleanup, retain_runtime=retain_runtime)

        logger.info(f"[{self.channel_type.value}] 交易执行完成 - 成功: {result.success}")

        return result

    def _normalize_standard_input_symbols(self, standard_input: UnifiedStandardInput) -> UnifiedStandardInput:
        """在进入算法前统一归一化 CTP 相关符号键和值."""
        symbol_changes: dict[str, str] = {}
        normalized_curr_target = self._normalize_weight_mapping(standard_input.curr_target, symbol_changes)
        normalized_last_target = self._normalize_weight_mapping(standard_input.last_target, symbol_changes)
        normalized_trade_rules = self._normalize_trade_rules(standard_input.trade_rules, symbol_changes)
        normalized_forbidden_symbols = self._normalize_symbol_list(standard_input.forbidden_symbols, symbol_changes)
        normalized_risk_symbols = self._normalize_symbol_list(standard_input.risk_symbols, symbol_changes)
        # CTP 账户里可能存在“输入里没写，但账户里还有暴露”的老持仓；这里显式补 0，
        # 让通用 planning 能把它们纳入本次执行的平仓集合。
        normalized_curr_target, added_symbols = self._with_existing_position_zero_targets(
            curr_target=normalized_curr_target,
            symbol_changes=symbol_changes,
        )

        if added_symbols:
            logger.info(f"[{self.channel_type.value}] 已为账户已有持仓补充 0 target: {added_symbols}")

        if symbol_changes:
            logger.info(f"[{self.channel_type.value}] 已归一化输入品种: {symbol_changes}")

        return standard_input.model_copy(
            update={
                "curr_target": normalized_curr_target,
                "last_target": normalized_last_target,
                "trade_rules": normalized_trade_rules,
                "forbidden_symbols": normalized_forbidden_symbols,
                "risk_symbols": normalized_risk_symbols,
            }
        )

    def _with_existing_position_zero_targets(
        self,
        curr_target: dict[str, float],
        symbol_changes: dict[str, str],
    ) -> tuple[dict[str, float], list[str]]:
        """为账户已有持仓但未出现在输入中的品种补 0 target."""
        normalized_curr_target = dict(curr_target)
        added_symbols: list[str] = []

        for symbol in self._get_existing_position_symbols():
            normalized_symbol = self._normalize_ctp_symbol(symbol)
            if normalized_symbol != symbol:
                symbol_changes[symbol] = normalized_symbol

            if normalized_symbol in normalized_curr_target:
                continue

            normalized_curr_target[normalized_symbol] = 0.0
            added_symbols.append(normalized_symbol)

        return normalized_curr_target, added_symbols

    def _get_existing_position_symbols(self) -> list[str]:
        """获取账户当前有持仓暴露的合约代码列表."""
        if not self.trader or not hasattr(self.trader, "get_positions_summary"):
            return []

        try:
            positions_summary = self.trader.get_positions_summary()
        except Exception as exc:
            logger.warning(f"[{self.channel_type.value}] 获取账户持仓摘要失败，跳过补 0 target: {exc}")
            return []

        symbols: list[str] = []
        seen: set[str] = set()
        for position in positions_summary:
            if not isinstance(position, dict):
                continue

            instrument_id = position.get("instrument_id")
            if not isinstance(instrument_id, str) or not instrument_id:
                continue

            if not self._position_has_exposure(position):
                continue

            if instrument_id in seen:
                continue

            symbols.append(instrument_id)
            seen.add(instrument_id)

        return symbols

    @staticmethod
    def _position_has_exposure(position: dict[str, Any]) -> bool:
        """判断持仓摘要是否仍有实际仓位暴露."""
        exposure_fields = ("net_position", "long_position", "short_position")
        for field in exposure_fields:
            raw_value = position.get(field, 0)
            if isinstance(raw_value, (int, float)) and raw_value != 0:
                return True
        return False

    def _normalize_weight_mapping(
        self,
        weights: dict[str, float],
        symbol_changes: dict[str, str],
    ) -> dict[str, float]:
        """归一化 symbol->weight 映射；冲突时按同一标准符号合并权重."""
        normalized: dict[str, float] = {}
        for symbol, weight in weights.items():
            normalized_symbol = self._normalize_ctp_symbol(symbol)
            if normalized_symbol != symbol:
                symbol_changes[symbol] = normalized_symbol
            normalized[normalized_symbol] = normalized.get(normalized_symbol, 0.0) + weight
        return normalized

    def _normalize_trade_rules(
        self,
        trade_rules: dict[str, dict[str, Any]],
        symbol_changes: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        """归一化交易规则的 symbol 键；冲突时以后出现的规则覆盖前者."""
        normalized: dict[str, dict[str, Any]] = {}
        for symbol, rule in trade_rules.items():
            normalized_symbol = self._normalize_ctp_symbol(symbol)
            if normalized_symbol != symbol:
                symbol_changes[symbol] = normalized_symbol
            normalized[normalized_symbol] = dict(rule)
        return normalized

    def _normalize_symbol_list(self, symbols: list[str], symbol_changes: dict[str, str]) -> list[str]:
        """归一化符号列表并保持原有顺序去重."""
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            normalized_symbol = self._normalize_ctp_symbol(symbol)
            if normalized_symbol != symbol:
                symbol_changes[symbol] = normalized_symbol
            if normalized_symbol in seen:
                continue
            normalized.append(normalized_symbol)
            seen.add(normalized_symbol)
        return normalized

    def _normalize_ctp_symbol(self, symbol: str) -> str:
        """将主力合约码和套利码转换为可交易的 CTP 合约代码."""
        stripped_symbol = symbol.strip()
        instruments = getattr(self.trader, "instruments", {}) if self.trader else {}

        if stripped_symbol in instruments:
            return stripped_symbol

        spread_symbol = self._strip_spread_prefix(stripped_symbol)
        if spread_symbol in instruments:
            return spread_symbol

        if spread_symbol.endswith("9001"):
            try:
                main_contract_symbol = format_symbol(spread_symbol)
            except Exception as exc:
                logger.warning(f"[{self.channel_type.value}] 主力合约转换失败，保留原始代码 {spread_symbol}: {exc}")
                return spread_symbol

            return main_contract_symbol

        return spread_symbol

    @staticmethod
    def _strip_spread_prefix(symbol: str) -> str:
        """去掉套利品种的人类可读前缀，保留 CTP 实际可订阅代码."""
        if "&" not in symbol:
            return symbol

        prefix, separator, remainder = symbol.partition(" ")
        if separator and prefix.upper() in {"SP", "SPD", "IPS"} and remainder:
            return remainder.strip()

        return symbol

    @override
    def _get_operation_display(self, order: UnifiedOrder) -> str:
        """
        重写操作显示文本方法，提供CTP特定的操作类型.

        Parameters
        ----------
        order : UnifiedOrder
            订单对象。

        Returns
        -------
        str
            CTP 特定的操作类型文本，例如 ``"开多"``、``"平空"``。
        """
        # 从订单的extra字段中获取CTP特定信息
        ctp_info = order.extra or {}
        offset_flag = ctp_info.get("offset_flag", "")

        # 基础方向判断
        direction = "买" if order.direction == OrderDirection.BUY else "卖"

        # 根据offset_flag确定具体操作类型
        if offset_flag == OffsetFlagType.OPEN.value or offset_flag == "0":
            if order.direction == OrderDirection.BUY:
                return "开多"
            else:
                return "开空"
        elif offset_flag in [
            OffsetFlagType.CLOSE.value,
            OffsetFlagType.CLOSE_TODAY.value,
            OffsetFlagType.CLOSE_YESTERDAY.value,
        ] or offset_flag in ["1", "3", "4"]:
            if order.direction == OrderDirection.BUY:
                return "平空"
            else:
                return "平多"
        else:
            # 默认情况，简单返回买卖方向
            return direction

    # ==================== UnifiedCallbackClient 接口实现 ====================

    @override
    def register_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注册订单更新回调函数.

        实现 UnifiedCallbackClient 接口。
        委托给 CtpTrader 处理回调注册。

        Parameters
        ----------
        callback : OrderUpdateCallback
            符合 ``OrderUpdateCallback`` 协议的回调函数。

        Examples
        --------
        >>> def handle_order(order: UnifiedOrder):
        ...     print(f"订单状态: {order.status}")
        >>> executor.register_order_callback(handle_order)
        """
        if not self.trader:
            logger.warning(f"[{self.channel_type.value}] 无法注册订单回调：CTP交易客户端未初始化")
            return
        self.trader.register_order_callback(callback)

    @override
    def register_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注册成交记录回调函数.

        实现 UnifiedCallbackClient 接口。
        委托给 CtpTrader 处理回调注册。

        Parameters
        ----------
        callback : TradeRecordCallback
            符合 ``TradeRecordCallback`` 协议的回调函数。

        Examples
        --------
        >>> def handle_trade(trade: TradeRecord):
        ...     print(f"成交价格: {trade.trade_price}")
        >>> executor.register_trade_callback(handle_trade)
        """
        if not self.trader:
            logger.warning(f"[{self.channel_type.value}] 无法注册成交回调：CTP交易客户端未初始化")
            return
        self.trader.register_trade_callback(callback)

    @override
    def is_monitoring(self) -> bool:
        """
        检查是否正在监控.

        实现 UnifiedCallbackClient 接口。
        返回 CTP 交易客户端的连接状态。

        Returns
        -------
        bool
            如果交易客户端已连接且已登录则返回 ``True``，否则返回 ``False``。

        Examples
        --------
        >>> if executor.is_monitoring():
        ...     print("CTP客户端正在监控事件")
        """
        if not self.trader:
            return False
        return self.trader.connected and self.trader.logged_in

    @override
    def stop(self) -> None:
        """
        停止回调客户端并清理资源.

        实现 UnifiedCallbackClient 接口。
        关闭 CTP 连接并清理资源。

        Notes
        -----
        此方法会停止 CTP 连接；停止后需要重新初始化才能继续使用回调功能。

        Examples
        --------
        >>> executor.stop()
        >>> print("CTP回调客户端已停止")
        """
        logger.info(f"[{self.channel_type.value}] 停止 UnifiedCallbackClient...")
        # 注意：AbstractExecutor.execute 会在每次执行结束调用 _cleanup。
        # 为了避免每次 execute 后断开连接，这里在 stop() 里显式关闭连接。
        try:
            if self.md_client:
                try:
                    self.md_client.close()
                except Exception as e:
                    logger.warning(f"[{self.channel_type.value}] 行情连接关闭失败: {e}")
                finally:
                    self.md_client = None

            if self.trader:
                try:
                    self.trader.close()
                except Exception as e:
                    logger.warning(f"[{self.channel_type.value}] 交易连接关闭失败: {e}")
                finally:
                    self.trader = None
        finally:
            self._cleanup()
        logger.info(f"[{self.channel_type.value}] UnifiedCallbackClient 已停止")

    # ===== 可选扩展接口实现 =====

    @override
    def unregister_order_callback(self, callback: OrderUpdateCallback) -> None:
        """
        注销订单更新回调函数.

        Parameters
        ----------
        callback : OrderUpdateCallback
            要注销的回调函数。
        """
        if self.trader:
            self.trader.unregister_order_callback(callback)

    @override
    def unregister_trade_callback(self, callback: TradeRecordCallback) -> None:
        """
        注销成交记录回调函数.

        Parameters
        ----------
        callback : TradeRecordCallback
            要注销的回调函数。
        """
        if self.trader:
            self.trader.unregister_trade_callback(callback)

    @override
    def get_callback_count(self) -> dict[str, int]:
        """
        获取当前注册的回调函数数量.

        Returns
        -------
        dict[str, int]
            包含 ``order_callbacks`` 与 ``trade_callbacks`` 计数的字典。
        """
        if not self.trader:
            return {"order_callbacks": 0, "trade_callbacks": 0}
        return self.trader.get_callback_count()

    # ==================== 回调相关方法 ====================

    def register_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注册价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            符合 ``PriceDataCallback`` 协议的回调函数。

        Examples
        --------
        >>> def handle_price(price: UnifiedPriceData):
        ...     print(f"价格更新: {price.symbol} @ {price.last_price}")
        >>> executor.register_price_callback(handle_price)
        """
        if not self.md_client:
            logger.warning(f"[{self.channel_type.value}] 无法注册价格回调：CTP行情客户端未初始化")
            return
        self.md_client.register_price_callback(callback)

    def unregister_price_callback(self, callback: PriceDataCallback) -> None:
        """
        注销价格数据回调函数.

        Parameters
        ----------
        callback : PriceDataCallback
            要注销的回调函数。
        """
        if self.md_client:
            self.md_client.unregister_price_callback(callback)

    def initialize_websocket(self, symbols: list[str] | None = None) -> None:
        """
        初始化行情订阅（对于CTP即订阅行情数据）.

        对于 CTP 执行器，此方法订阅指定品种的行情数据。
        行情数据通过 CTP 行情客户端接收，支持价格回调。

        Parameters
        ----------
        symbols : list[str] | None, optional
            需要订阅行情的品种代码列表。

        Examples
        --------
        >>> executor.initialize_websocket(["rb2505", "hc2505"])
        """
        if not self.md_client:
            logger.warning(f"[{self.channel_type.value}] 无法初始化行情订阅：CTP行情客户端未初始化")
            return

        if symbols:
            logger.info(f"[{self.channel_type.value}] 初始化行情订阅，品种: {symbols}")
            self.md_client.subscribe(symbols)

    def _cancel_order_impl(self, symbol: str, order_id: str) -> bool:
        """
        撤销指定订单.

        根据品种代码和订单ID撤销指定的订单。

        Parameters
        ----------
        symbol : str
            品种代码。
        order_id : str
            订单 ID，对应 ``UnifiedOrder.order_id``。

        Returns
        -------
        bool
            撤销成功时返回 ``True``，否则返回 ``False``。

        Examples
        --------
        >>> success = executor.cancel_order("rb2505", "123456")
        >>> if success:
        ...     print("撤单成功")
        """
        if not self.trader:
            logger.error(f"[{self.channel_type.value}] 无法撤单：CTP交易客户端未连接")
            return False

        try:
            # 从 trader.orders 中查找订单
            # order_id 对应 OrderRef
            order = None
            for ref, ord in self.trader.orders.items():
                if str(ref) == order_id and ord.InstrumentID == symbol:
                    order = ord
                    break

            if not order:
                logger.warning(f"[{self.channel_type.value}] 未找到订单: {symbol} order_id={order_id}")
                return False

            # 调用 trader 的撤单方法
            success = self.trader.cancel_order(order)
            if success:
                logger.info(f"[{self.channel_type.value}] 撤单请求已发送: {symbol} order_id={order_id}")
            else:
                logger.error(f"[{self.channel_type.value}] 撤单请求失败: {symbol} order_id={order_id}")
            return success

        except Exception as e:
            logger.error(f"[{self.channel_type.value}] 撤单异常: {symbol} order_id={order_id}, 错误: {e}")
            return False

    @override
    def _query_trades_impl(self, symbol: str, order_id: str) -> list[TradeRecord]:
        """获取指定订单的成交明细."""
        if not self.trader:
            raise RuntimeError("CTP交易客户端未连接")

        trade_map = self.trader._query_trades_impl(symbol)

        matched_trades: list[TradeRecord] = []
        for trade in trade_map.values():
            if trade.InstrumentID != symbol:
                continue

            candidate_ids = {
                str(getattr(trade, "OrderSysID", "") or ""),
                str(getattr(trade, "OrderRef", "") or ""),
            }
            if order_id not in candidate_ids:
                continue

            matched_trades.append(trade.to_unified_trade())

        return matched_trades

    @override
    def _get_execution_trades_snapshot_fetcher(self):
        """返回 Execution 内部共享的 CTP 远端成交快照."""
        return lambda: self._run_execution_shared_fetch(
            operation="query_trades",
            shared_query_key=("trades_snapshot",),
            query_scope="snapshot",
            fetcher=self._fetch_trade_records_snapshot_for_execution,
        )

    def _fetch_trade_records_snapshot_for_execution(self) -> list[TradeRecord]:
        """拉取当前 execution 可见的全部 CTP 成交并补齐统一过滤元数据."""
        if not self.trader:
            raise RuntimeError("CTP交易客户端未连接")

        trade_map = self.trader._query_trades_impl("")

        trade_records: list[TradeRecord] = []
        for trade in trade_map.values():
            trade_record = trade.to_unified_trade()
            trade_record.extra = {
                **trade_record.extra,
                "symbol": str(getattr(trade, "InstrumentID", "") or ""),
                "order_id": str(getattr(trade, "OrderSysID", "") or ""),
                "order_ref": str(getattr(trade, "OrderRef", "") or ""),
                "order_id_candidates": [
                    str(getattr(trade, "OrderSysID", "") or ""),
                    str(getattr(trade, "OrderRef", "") or ""),
                ],
            }
            trade_records.append(trade_record)
        return trade_records

    def _register_execution_query_runtime_callback_observers(self) -> None:
        """注册 execution 共享查询失效观察者."""
        if getattr(self, "_execution_query_runtime_observers_registered", False):
            return
        if self.trader is None or not hasattr(self.trader, "_callback_manager"):
            return
        bridge = self.get_execution_query_runtime_bridge()
        self.trader._callback_manager.register_order_observer(bridge.observe_order_update)
        self.trader._callback_manager.register_trade_observer(bridge.observe_trade_record)
        self._execution_query_runtime_observers_registered = True

    @override
    def _calculate_generic_volume(
        self,
        weight: float,
        price: float,
        account_assets: UnifiedAccountAssets,
        trade_rule: dict[str, object],
        *,
        symbol: str | None = None,
    ) -> float:
        """
        CTP 渠道下"权重 → 目标手数"换算的统一入口.

        将合约乘数 (``VolumeMultiple``) 收敛到 CTP 实现内部，避免上层算法
        因为漏乘乘数把目标手数放大成 N 倍。期权与期货共享同一种 sizing
        语义；如需直接传"张数"，可在 ``trade_rule`` 中显式指定
        ``sizing_mode='lots'``。

        Parameters
        ----------
        weight : float
            目标仓位权重（``sizing_mode='weight'/'premium_weight'`` 时）
            或目标手数（``sizing_mode='lots'`` 时）。
        price : float
            最新价格；价格 ``<= 0`` 时直接返回 ``0``。
        account_assets : UnifiedAccountAssets
            当前账户资产快照。
        trade_rule : dict[str, object]
            品种交易规则；可选键:

            - ``sizing_mode``: ``"weight"``（期货默认）/
              ``"premium_weight"``（期权默认，按权利金权重换算）/
              ``"lots"``（直接当目标手数）。
            - ``contract_multiplier``: 合约乘数 fallback；
              在 ``self.trader.instruments`` 缺失时使用。
            - ``最小交易单位`` / ``quantity_precision``: 取整规则。
        symbol : str | None, optional
            正在计算的品种代码，用于读取合约缓存。

        Returns
        -------
        float
            按 CTP 公式换算并取整后的目标手数。

        Notes
        -----
        - 期货公式: ``target = total_asset * weight / (price * VolumeMultiple)``
        - 期权 ``premium_weight``: 与期货同公式，按权利金权重配置。
        - 期权 ``lots``: ``target = weight``（直接当手数，仅在 trade_rule
          显式声明时生效，避免策略层把 0.05 (5%) 当成 5 手的量级风险）。
        """
        sizing_mode_raw = trade_rule.get("sizing_mode", "weight")
        sizing_mode = str(sizing_mode_raw) if isinstance(sizing_mode_raw, str) else "weight"

        if sizing_mode == "lots":
            return self._round_lots(weight, trade_rule)

        if price <= 0:
            return 0.0

        volume_multiple = self._resolve_volume_multiple(symbol, trade_rule)
        if volume_multiple <= 0:
            return 0.0

        # 期货 weight / 期权 premium_weight 当前共用同一公式：按权利金 / 名义价值权重换算。
        target = account_assets.total_asset * weight / (price * volume_multiple)
        return self._round_lots(target, trade_rule)

    def _resolve_volume_multiple(self, symbol: str | None, trade_rule: dict[str, object]) -> int:
        """
        解析品种合约乘数，优先读 ``trader.instruments``，trade_rule 兜底.

        Parameters
        ----------
        symbol : str | None
            品种代码；为 ``None`` 时跳过合约缓存查询。
        trade_rule : dict[str, object]
            交易规则；可通过 ``contract_multiplier`` 键提供 fallback。

        Returns
        -------
        int
            解析得到的合约乘数；缺失或非法时返回 ``0``。
        """
        if symbol and self.trader is not None:
            instrument = self.trader.instruments.get(symbol)
            if instrument is not None and instrument.VolumeMultiple > 0:
                return int(instrument.VolumeMultiple)

        fallback = trade_rule.get("contract_multiplier")
        if isinstance(fallback, int | float) and not isinstance(fallback, bool) and fallback > 0:
            return int(fallback)
        return 0

    @staticmethod
    def _round_lots(volume: float, trade_rule: dict[str, object]) -> float:
        """
        按 ``trade_rule`` 中的取整规则将原始手数对齐到合法值.

        Parameters
        ----------
        volume : float
            未取整的目标手数。
        trade_rule : dict[str, object]
            交易规则；支持 ``quantity_precision``（保留小数位）与
            ``最小交易单位``（向下取最小整数倍）。

        Returns
        -------
        float
            取整后的目标手数；正负号保持不变。

        Notes
        -----
        正负号语义在算法层处理；本函数仅做绝对值取整。
        """
        precision_raw = trade_rule.get("quantity_precision")
        precision = precision_raw if isinstance(precision_raw, int) and not isinstance(precision_raw, bool) else None

        min_volume_raw = trade_rule.get("最小交易单位", 1)
        min_volume = (
            float(min_volume_raw)
            if isinstance(min_volume_raw, int | float) and not isinstance(min_volume_raw, bool)
            else 1.0
        )

        if precision is not None:
            return round(volume, precision)
        if min_volume > 1:
            sign = 1.0 if volume >= 0 else -1.0
            return sign * (int(abs(volume) / min_volume) * min_volume)
        # 默认按整数手数取整，与 CTP 旧版 ``int(...)`` 保持一致。
        return float(int(volume)) if volume >= 0 else float(-int(-volume))

    # ==================== 期权行权 / 放弃 / 自对冲 ====================

    def submit_option_action(
        self,
        *,
        symbol: str,
        action: str,
        volume: int,
        trade_rule: dict[str, object] | None = None,
    ) -> OptionActionRecord:
        """
        提交期权行权 / 放弃 / 自对冲指令.

        Parameters
        ----------
        symbol : str
            期权合约代码。
        action : str
            指令类型，``"exercise"`` / ``"abandon"`` / ``"self_close"``。
        volume : int
            张数（必须为正整数）。
        trade_rule : dict[str, object] | None, optional
            交易规则；当前未参与计算，预留扩展位。

        Returns
        -------
        OptionActionRecord
            状态机快照（已登记的 Pending 状态）。可通过
            ``get_option_action_status(record.order_ref)`` 持续轮询直到
            进入终态。

        Raises
        ------
        RuntimeError
            CTP 交易客户端未连接。
        ValueError
            volume 非正、合约不存在、合约不是期权、action 取值非法。
        """
        if not self.trader:
            raise RuntimeError("CTP 交易客户端未连接")

        try:
            action_enum = OptionActionType(action)
        except ValueError as exc:
            raise ValueError(f"非法 action={action!r}; 合法取值为 'exercise' / 'abandon' / 'self_close'") from exc

        # P0-1 修复：常规 query_instruments 默认过滤期权，导致 self.instruments 不含期权。
        # submit_option_action 入口处按需懒加载期权合约，避免 option_action() 必抛
        # "未找到期权合约"。
        cached = self.trader.instruments.get(symbol)
        if cached is None or cached.ProductClass != "2":
            self.logger.info(f"🔄 期权合约 {symbol} 未在缓存中，触发 query_option_instruments")
            self.trader.query_option_instruments(instrument_id=symbol)

        order_ref = self.trader.option_action(
            instrument_id=symbol,
            action=action_enum,
            volume=int(volume),
            trade_rule=trade_rule,
        )
        record = self.trader.get_option_action_status(order_ref)
        if record is None:
            raise RuntimeError(f"期权指令登记后无法查到状态: ref={order_ref}")
        return record

    def cancel_option_action(self, order_ref: str) -> bool:
        """
        撤销已提交但未受理的期权行权指令.

        Parameters
        ----------
        order_ref : str
            ``submit_option_action`` 返回 record 中的 ``order_ref``。

        Returns
        -------
        bool
            撤销请求是否发送成功；后续状态机将由
            ``OnRspExecOrderAction`` / ``OnRtnExecOrder`` 推进。
        """
        if not self.trader:
            return False
        return self.trader.cancel_option_action(order_ref)

    def get_option_action_status(self, order_ref: str) -> OptionActionRecord | None:
        """读取行权指令的状态机快照."""
        if not self.trader:
            return None
        return self.trader.get_option_action_status(order_ref)

    def is_exercise_valuable(self, symbol: str) -> bool:
        """
        判断当前行情下行权是否有内在价值.

        Parameters
        ----------
        symbol : str
            期权合约代码。

        Returns
        -------
        bool
            看涨期权：标的最新价 > 行权价 时有价值；
            看跌期权：标的最新价 < 行权价 时有价值；
            其它情况（合约缺失 / 行情缺失 / 非期权）返回 ``False`` 以避免
            盲目行权。
        """
        if not self.trader or not self.md_client:
            return False

        instrument = self.trader.instruments.get(symbol)
        if not is_option(instrument) or instrument is None:
            return False

        underlying = instrument.UnderlyingInstrID
        if not underlying:
            return False

        quote = self.md_client.get_quote(underlying)
        if quote is None or quote.LastPrice <= 0:
            self.logger.warning(f"⚠️ 期权 {symbol} 标的 {underlying} 行情缺失，无法判断行权价值")
            return False

        last_price = float(quote.LastPrice)
        strike = float(instrument.StrikePrice)

        if is_option_call(instrument):
            return last_price > strike
        # 看跌
        return last_price < strike

    @staticmethod
    def is_option_action_terminal(record: OptionActionRecord) -> bool:
        """状态机便捷判断：record 是否进入终态。"""
        return record.status in {
            OptionActionStatus.EXECUTED,
            OptionActionStatus.ABANDONED,
            OptionActionStatus.CANCELLED,
            OptionActionStatus.FAILED,
        }
