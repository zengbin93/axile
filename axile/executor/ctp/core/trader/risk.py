"""``CtpTrader`` 风控、保证金计算与下单前校验 mixin."""

# Mixin 共享属性（self.logger / self.account / self.instruments / self.risk_config 等）
# 由 _main.py 的 __init__ 初始化，pyright 无法静态推断；用文件级
# reportAttributeAccessIssue 抑制。
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from collections import defaultdict
from typing import Any

from axile.executor.ctp.core.openctp_compat import (
    THOST_FTDC_D_Buy,
    THOST_FTDC_D_Sell,
    THOST_FTDC_OF_CloseToday,
    THOST_FTDC_OF_CloseYesterday,
    THOST_FTDC_OF_Open,
)
from axile.executor.ctp.core.trader._constants import OperationCounter, get_default_clock


class RiskMixin:
    """风控配置、操作频率与下单前 verify_*。"""

    def _record_operation(self, operation_type: str):
        """记录操作到历史记录中."""
        with self.risk_control_lock:
            current_time = get_default_clock().time()
            self.operation_history.append(OperationCounter(timestamp=current_time, operation_type=operation_type))

    def _check_operation_frequency(self, operation_type: str) -> tuple[bool, str]:
        """
        检查操作频率是否超过阈值.

        Parameters
        ----------
        operation_type : str
            操作类型，例如 ``"query"`` 或 ``"order"``。

        Returns
        -------
        tuple[bool, str]
            是否通过检查，以及对应的错误信息。
        """
        with self.risk_control_lock:
            current_time = get_default_clock().time()
            minute_ago = current_time - 60.0

            # 清理过期记录（超过1分钟的）
            while self.operation_history and self.operation_history[0].timestamp < minute_ago:
                self.operation_history.popleft()

            # 统计各类操作的次数
            operation_counts: dict[str, int] = defaultdict(int)
            for record in self.operation_history:
                operation_counts[record.operation_type] += 1

            # 检查对应的阈值
            current_count = operation_counts[operation_type]

            if operation_type == "query":
                max_count = self.risk_config.max_queries_per_minute
                operation_desc = "查询"
            elif operation_type == "order":
                max_count = self.risk_config.max_orders_per_minute
                operation_desc = "委托"
            else:
                return True, "未知操作类型"

            if current_count >= max_count:
                return (
                    False,
                    (
                        f"❌ {operation_desc}频率超限：1分钟内已{operation_desc} {current_count} 次，"
                        f"超过限制 {max_count} 次/分钟"
                    ),
                )

            self.logger.debug(f"✅ {operation_desc}频率检查通过：{current_count}/{max_count} 次/分钟")
            return True, "频率检查通过"

    def _check_order_volume(self, instrument_id: str, volume: int, offset: str) -> tuple[bool, str]:
        """
        检查报单数量是否异常.

        Parameters
        ----------
        instrument_id : str
            合约代码。
        volume : int
            委托数量。
        offset : str
            开平标志。

        Returns
        -------
        tuple[bool, str]
            是否通过检查，以及对应的错误信息。
        """
        # 1. 检查单笔委托数量范围
        if volume < self.risk_config.min_order_volume:
            return (
                False,
                f"❌ 委托数量过小：{volume}手 < 最小限制 {self.risk_config.min_order_volume}手",
            )

        if volume > self.risk_config.max_order_volume:
            return (
                False,
                f"❌ 委托数量过大：{volume}手 > 最大限制 {self.risk_config.max_order_volume}手",
            )

        # 2. 检查开仓后的总持仓是否超限（仅对开仓订单检查）
        if offset == THOST_FTDC_OF_Open:
            position_info = self.get_position_info(instrument_id)
            long_pos = int(position_info["long_position"])
            short_pos = int(position_info["short_position"])
            current_total = long_pos + short_pos
            future_total = current_total + volume

            if future_total > self.risk_config.max_total_position:
                return (
                    False,
                    (
                        f"❌ 总持仓将超限：当前持仓 {current_total}手 + 开仓 {volume}手 = {future_total}手 "
                        f"> 最大限制 {self.risk_config.max_total_position}手"
                    ),
                )

        self.logger.debug(
            f"✅ 委托数量检查通过：{volume}手 "
            f"(范围 {self.risk_config.min_order_volume}-{self.risk_config.max_order_volume})"
        )
        return True, "数量检查通过"

    def _check_order_rate(self) -> tuple[bool, str]:
        """
        检查报单速率是否异常.

        Returns
        -------
        tuple[bool, str]
            是否通过检查，以及对应的错误信息。
        """
        current_time = get_default_clock().time()
        time_since_last = 0.0  # 初始化变量，避免未定义错误

        # 1. 检查最小报单间隔
        if self.last_order_time > 0:
            time_since_last = current_time - self.last_order_time
            if time_since_last < self.risk_config.min_order_interval:
                wait_time = self.risk_config.min_order_interval - time_since_last
                return (
                    False,
                    (
                        f"❌ 报单间隔过短：距离上次报单仅 {time_since_last:.2f}秒，"
                        f"最小间隔要求 {self.risk_config.min_order_interval}秒，需等待 {wait_time:.2f}秒"
                    ),
                )
        else:
            # 第一次下单的情况
            self.logger.debug("首次下单，跳过间隔检查")

        # 2. 检查每秒报单数量
        with self.risk_control_lock:
            second_ago = current_time - 1.0
            recent_orders = [
                op for op in self.operation_history if op.operation_type == "order" and op.timestamp > second_ago
            ]

            if len(recent_orders) >= self.risk_config.max_orders_per_second:
                return (
                    False,
                    (
                        f"❌ 报单速率过快：1秒内已报单 {len(recent_orders)} 次，"
                        f"超过限制 {self.risk_config.max_orders_per_second} 次/秒"
                    ),
                )

        # 修复：根据情况显示不同的日志
        if self.last_order_time > 0:
            self.logger.debug(
                f"✅ 报单速率检查通过：间隔 {time_since_last:.2f}秒 >= {self.risk_config.min_order_interval}秒"
            )
        else:
            self.logger.debug("✅ 报单速率检查通过：首次下单")

        return True, "报单速率检查通过"

    def _check_order_price(self, instrument_id: str, limit_price: float) -> tuple[bool, str]:
        """
        检查报单价格是否异常.

        Parameters
        ----------
        instrument_id : str
            合约代码。
        limit_price : float
            委托价格。

        Returns
        -------
        tuple[bool, str]
            是否通过检查，以及对应的错误信息。
        """
        # 1. 获取合约信息
        if instrument_id not in self.instruments:
            return False, f"❌ 合约 {instrument_id} 信息未找到，无法进行价格检查"

        instrument = self.instruments[instrument_id]

        # 3. 检查价格范围（涨跌停）
        if self.risk_config.enable_limit_price_check:
            # 注意：这里需要实时行情数据来获取涨跌停价格
            # 如果没有行情数据，我们可以用合约的上下限价格
            upper_limit_price = getattr(instrument, "UpperLimitPrice", 0)
            if upper_limit_price > 0:
                if limit_price > upper_limit_price:
                    return False, (f"❌ 委托价格超过涨停价：{limit_price} > {upper_limit_price}")

            lower_limit_price = getattr(instrument, "LowerLimitPrice", 0)
            if lower_limit_price > 0:
                if limit_price < lower_limit_price:
                    return False, (f"❌ 委托价格低于跌停价：{limit_price} < {lower_limit_price}")

        # 4. 检查价格合理性（基于历史价格或昨收价）
        reference_price = None
        pre_close_price = getattr(instrument, "PreClosePrice", 0)
        pre_settlement_price = getattr(instrument, "PreSettlementPrice", 0)
        if pre_close_price > 0:
            reference_price = pre_close_price
        elif pre_settlement_price > 0:
            reference_price = pre_settlement_price

        if reference_price and reference_price > 0:
            deviation = abs(limit_price - reference_price) / reference_price
            if deviation > self.risk_config.max_price_deviation:
                return (
                    False,
                    (
                        f"❌ 价格偏离过大：{limit_price} 相对参考价 {reference_price} "
                        f"偏离 {deviation:.2%} > 限制 {self.risk_config.max_price_deviation:.2%}"
                    ),
                )

        # 5. 基本合理性检查
        if limit_price <= 0:
            return False, f"❌ 委托价格必须大于0：{limit_price}"

        self.logger.debug(f"✅ 价格检查通过：{limit_price} (最小变动价位={instrument.PriceTick})")
        return True, "价格检查通过"

    def verify_insert_order(
        self,
        instrument_id: str,
        direction: str,
        offset: str,
        limit_price: float,
        volume: int,
        *,
        trade_rule: dict[str, object] | None = None,
    ) -> tuple[bool, str]:
        """
        风控验证：检查下单前的风控要求.

        Parameters
        ----------
        instrument_id : str
            合约代码。
        direction : str
            交易方向（CTP 协议字符串）。
        offset : str
            开平标志（CTP 协议字符串）。
        limit_price : float
            委托价格。
        volume : int
            委托数量。
        trade_rule : dict[str, object] | None, optional
            品种交易规则；用于在 CTP 合约表保证金率为 0 时提供
            ``margin_ratio`` 兜底（典型场景：期权卖方）。

        Returns
        -------
        tuple[bool, str]
            ``(是否通过, 备注信息)``。
        """
        try:
            # 基础风控检查
            is_valid, error_msg = self._verify_basic_risk(instrument_id, direction, offset, limit_price, volume)
            if not is_valid:
                return False, error_msg

            # 资金和仓位验证
            is_valid, error_msg = self._verify_fund_and_position(
                instrument_id, direction, offset, limit_price, volume, trade_rule=trade_rule
            )
            if not is_valid:
                return False, error_msg

            return True, "验证通过"

        except (
            AttributeError,
            KeyError,
            LookupError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            error_msg = f"验资验仓过程中发生异常: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def _verify_basic_risk(
        self,
        instrument_id: str,
        _direction: str,
        offset: str,
        limit_price: float,
        volume: int,
    ) -> tuple[bool, str]:
        """基础风控检查."""
        # 检查操作频率
        is_valid, error_msg = self._check_operation_frequency("order")
        if not is_valid:
            return False, error_msg

        # 检查报单数量
        is_valid, error_msg = self._check_order_volume(instrument_id, volume, offset)
        if not is_valid:
            return False, error_msg

        # 检查报单速率
        is_valid, error_msg = self._check_order_rate()
        if not is_valid:
            return False, error_msg

        # 检查报单价格
        is_valid, error_msg = self._check_order_price(instrument_id, limit_price)
        if not is_valid:
            return False, error_msg

        return True, "基础风控检查通过"

    def _verify_fund_and_position(
        self,
        instrument_id: str,
        direction: str,
        offset: str,
        limit_price: float,
        volume: int,
        *,
        trade_rule: dict[str, object] | None = None,
    ) -> tuple[bool, str]:
        """资金和仓位验证."""
        # 检查合约和账户信息
        if instrument_id not in self.instruments:
            return False, f"合约 {instrument_id} 信息未找到，请先查询合约信息"

        if not self.account:
            return False, "账户信息未找到，请先查询账户信息"

        # 开仓验资或平仓验仓
        if offset == THOST_FTDC_OF_Open:
            return self._verify_open_position_fund(instrument_id, direction, limit_price, volume, trade_rule=trade_rule)
        else:
            return self._verify_close_position_fund(instrument_id, direction, offset, volume)

    def _verify_open_position_fund(
        self,
        instrument_id: str,
        direction: str,
        limit_price: float,
        volume: int,
        *,
        trade_rule: dict[str, object] | None = None,
    ) -> tuple[bool, str]:
        """验证开仓资金."""
        if not self.account:
            return False, "账户信息未找到，请先查询账户信息"
        required_margin = self.calculate_required_margin(
            instrument_id, direction, limit_price, volume, trade_rule=trade_rule
        )
        available_fund = self.account.Available

        if available_fund < required_margin:
            return (
                False,
                (
                    f"❌ 资金不足：开仓 {instrument_id} {volume}手需要保证金 {required_margin:,.2f}元，"
                    f"可用资金仅 {available_fund:,.2f}元，缺口 {required_margin - available_fund:,.2f}元"
                ),
            )

        self.logger.info(
            f"✅ 资金验证通过：{instrument_id} 开仓 {volume}手需保证金 {required_margin:,.2f}元，"
            f"可用资金 {available_fund:,.2f}元"
        )
        return True, "资金验证通过"

    def _verify_close_position_fund(
        self, instrument_id: str, direction: str, offset: str, volume: int
    ) -> tuple[bool, str]:
        """验证平仓仓位."""
        position_info = self.get_position_info(instrument_id)
        direction_desc, available_position, offset_desc = self._get_close_position_info(
            direction, offset, position_info
        )

        if available_position < volume:
            return (
                False,
                (
                    f"❌ 仓位不足：{instrument_id} {direction_desc} {offset_desc} 需要 {volume}手，"
                    f"可用仓位仅 {available_position}手，缺口 {volume - available_position}手\n"
                    f"   持仓详情：多头={position_info['long_position']}(昨{position_info['long_yd_position']}+今{position_info['long_today_position']}), "
                    f"空头={position_info['short_position']}(昨{position_info['short_yd_position']}+今{position_info['short_today_position']})"
                ),
            )

        self.logger.info(
            f"✅ 仓位验证通过：{instrument_id} {direction_desc} {offset_desc} {volume}手，可用仓位 {available_position}手"
        )
        return True, "仓位验证通过"

    def _get_close_position_info(
        self, direction: str, offset: str, position_info: dict[str, Any]
    ) -> tuple[str, int, str]:
        """获取平仓方向和可用仓位信息."""
        if direction == THOST_FTDC_D_Buy:
            # 买入平仓 = 平空头仓位
            direction_desc = "空头"
            if offset == THOST_FTDC_OF_CloseToday:
                return direction_desc, position_info["short_today_position"], "平今"
            elif offset == THOST_FTDC_OF_CloseYesterday:
                return direction_desc, position_info["short_yd_position"], "平昨"
            else:
                return direction_desc, position_info["short_position"], "平仓"
        elif direction == THOST_FTDC_D_Sell:
            # 卖出平仓 = 平多头仓位
            direction_desc = "多头"
            if offset == THOST_FTDC_OF_CloseToday:
                return direction_desc, position_info["long_today_position"], "平今"
            elif offset == THOST_FTDC_OF_CloseYesterday:
                return direction_desc, position_info["long_yd_position"], "平昨"
            else:
                return direction_desc, position_info["long_position"], "平仓"
        else:
            raise ValueError(f"未知的交易方向: {direction}")

    def calculate_required_margin(
        self,
        instrument_id: str,
        direction: str,
        limit_price: float,
        volume: int,
        *,
        trade_rule: dict[str, object] | None = None,
    ) -> float:
        """
        计算开仓所需保证金.

        Parameters
        ----------
        instrument_id : str
            合约代码。
        direction : str
            交易方向。
        limit_price : float
            价格。
        volume : int
            数量。
        trade_rule : dict[str, object] | None, optional
            品种交易规则，可选。当 CTP 合约表上 ``LongMarginRatio`` /
            ``ShortMarginRatio`` 为 0（部分期权 / 自定义合约场景）时，
            会回退到 ``trade_rule['margin_ratio']`` 提供的兜底比率。
            ``margin_ratio`` 为正实数（如 ``0.18`` 表示 18%）。

        Returns
        -------
        float
            所需保证金金额。

        Notes
        -----
        - 期货 / 期权买方：``required = price × volume × VolumeMultiple × ratio``
        - 期权卖方：与买方同公式，但 CTP 通常会在 ``ShortMarginRatio`` 上
          单独配置；当 CTP 返回 0 时必须由 ``trade_rule.margin_ratio`` 兜底，
          否则会被算成 0 保证金、放行无限杠杆。
        """
        if instrument_id not in self.instruments:
            self.logger.warning(f"合约 {instrument_id} 信息未找到")
            return 0.0

        instrument = self.instruments[instrument_id]
        margin_ratio = instrument.LongMarginRatio if direction == THOST_FTDC_D_Buy else instrument.ShortMarginRatio

        # CTP 合约表上保证金率为 0 时（部分期权或自定义合约），优先用 trade_rule 兜底，
        # 避免把所需保证金算成 0 而放行无限杠杆。
        if margin_ratio <= 0:
            fallback = (trade_rule or {}).get("margin_ratio")
            if isinstance(fallback, int | float) and not isinstance(fallback, bool) and fallback > 0:
                margin_ratio = float(fallback)
            else:
                self.logger.warning(
                    f"⚠️ 合约 {instrument_id} 方向 {direction} 的保证金率为 0 且 trade_rule 未提供 margin_ratio 兜底；"
                    f"required_margin 将被算成 0，可能导致无限杠杆，请显式配置 trade_rule.margin_ratio"
                )

        required_margin = limit_price * volume * instrument.VolumeMultiple * margin_ratio
        return required_margin

    def update_risk_config(self, **kwargs: object):
        """更新风控配置."""
        for key, value in kwargs.items():
            if hasattr(self.risk_config, key):
                setattr(self.risk_config, key, value)
                self.logger.info(f"✅ 风控配置已更新：{key} = {value}")
            else:
                self.logger.warning(f"⚠️  未知的风控配置项：{key}")

    def get_risk_status(self) -> dict[str, Any]:
        """获取当前风控状态."""
        with self.risk_control_lock:
            current_time = get_default_clock().time()
            minute_ago = current_time - 60.0

            operation_counts: dict[str, int] = defaultdict(int)
            for record in self.operation_history:
                if record.timestamp > minute_ago:
                    operation_counts[record.operation_type] += 1

            return {
                "config": {
                    "max_queries_per_minute": self.risk_config.max_queries_per_minute,
                    "max_orders_per_minute": self.risk_config.max_orders_per_minute,
                    "min_order_volume": self.risk_config.min_order_volume,
                    "max_order_volume": self.risk_config.max_order_volume,
                    "max_total_position": self.risk_config.max_total_position,
                    "min_order_interval": self.risk_config.min_order_interval,
                    "max_orders_per_second": self.risk_config.max_orders_per_second,
                    "max_price_deviation": self.risk_config.max_price_deviation,
                },
                "current_status": {
                    "queries_last_minute": operation_counts["query"],
                    "orders_last_minute": operation_counts["order"],
                    "last_order_time": self.last_order_time,
                    "time_since_last_order": current_time - self.last_order_time if self.last_order_time > 0 else None,
                    "operation_history_count": len(self.operation_history),
                },
            }

    def reset_risk_counters(self):
        """重置风控计数器."""
        with self.risk_control_lock:
            self.operation_history.clear()
            self.last_order_time = 0.0
            self.logger.warning("🔄 风控计数器已重置")

    def log_risk_status(self):
        """记录当前风控状态概览."""
        status = self.get_risk_status()

        self.logger.info("=" * 50)
        self.logger.info("🛡️  风控状态概览")
        self.logger.info("=" * 50)

        current = status["current_status"]
        config = status["config"]

        self.logger.info("📊 操作频率统计（最近1分钟）：")
        self.logger.info(f"   查询: {current['queries_last_minute']}/{config['max_queries_per_minute']} 次")
        self.logger.info(f"   委托: {current['orders_last_minute']}/{config['max_orders_per_minute']} 次")

        if current["time_since_last_order"]:
            self.logger.info(f"⏰ 最后报单距今: {current['time_since_last_order']:.2f}秒")

        self.logger.info(
            f"📈 委托限制: 数量 {config['min_order_volume']}-{config['max_order_volume']}手, "
            f"间隔 ≥{config['min_order_interval']}秒, "
            f"速率 ≤{config['max_orders_per_second']}次/秒"
        )

        self.logger.info(f"💰 价格限制: 偏离度 ≤{config['max_price_deviation']:.1%}")

        self.logger.info("=" * 50)
