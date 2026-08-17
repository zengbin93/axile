"""``CtpTrader`` 持仓查询、组合拆腿与持仓汇总 mixin."""

# Mixin 共享属性（self.logger / self.positions / self.account 等）由 _main.py
# 的 __init__ 初始化，pyright 无法静态推断；用文件级 reportAttributeAccessIssue
# 抑制。
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from axile.executor.account_control.decorators import controlled_operation
from axile.executor.ctp.core.combination_position_filter import (
    get_combination_info,
    is_combination_instrument,
    split_combination_position,
)
from axile.executor.ctp.core.objects import CtpConverter, PositionField, TradingAccountField
from axile.executor.ctp.core.openctp_compat import (
    CThostFtdcQryInvestorPositionField,
    CThostFtdcQryTradingAccountField,
)
from axile.executor.ctp.core.trader._constants import CTP_TD_GLOBAL_GROUP, _wait_or_raise


class PositionsMixin:
    """账户资金、持仓查询与组合拆腿."""

    @controlled_operation(
        "query_account",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    def query_account(self) -> TradingAccountField | None:
        """查询账户."""
        req = CThostFtdcQryTradingAccountField()
        req.BrokerID = self.broker
        req.InvestorID = self.user

        event_key = "account"
        self.query_events[event_key] = threading.Event()
        self.api.ReqQryTradingAccount(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            30,
            "查询账户超时",
            stop_event=self.stop_event,
        )
        return self.account

    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, _nRequestID, bIsLast):
        """查询账户响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询账户失败: {pRspInfo.ErrorMsg}")
            # 不要直接return，继续处理bIsLast

        elif pTradingAccount:
            # 转换为Pydantic模型
            account_model = CtpConverter.account_to_model(pTradingAccount)
            self.account = account_model

            # 详细日志，提高执行过程透明度
            self.logger.info(f"查询到账户资金信息:\n{account_model}")

        if bIsLast and "account" in self.query_events:
            self.query_events["account"].set()

    @controlled_operation(
        "query_positions",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    def query_positions(
        self,
        instrument_id: str = "",
    ) -> dict[str, PositionField]:
        """查询持仓."""
        # 每次全量查询前清空组合拆腿审计映射，避免上一轮已不存在的组合
        # 留下脏数据。按 instrument_id 子查询时仅清理对应 key，保持其它腿。
        if instrument_id:
            self.combination_origins.pop(instrument_id, None)
        else:
            self.combination_origins.clear()

        req = CThostFtdcQryInvestorPositionField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        if instrument_id:
            req.InstrumentID = instrument_id

        self.logger.info(f"开始查询持仓：{self.broker} - {self.user} - {instrument_id}")
        event_key = f"position_{instrument_id}"
        self.query_events[event_key] = threading.Event()
        self.api.ReqQryInvestorPosition(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            30,
            "查询持仓超时",
            stop_event=self.stop_event,
        )

        if instrument_id:
            pos = {k: v for k, v in self.positions.items() if k.startswith(instrument_id)}
            return pos

        return self.positions

    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, _nRequestID, bIsLast):
        """查询持仓响应.

        CTP 系统对于同一合约、同一方向的持仓，会按照持仓日期分别记录：
        PositionDate = '1': 今日持仓（Today）
        PositionDate = '2': 昨日持仓（Previous）
        PositionDate = '3': 其他日期持仓

        注意：CTP 会将套利持仓合并为组合持仓返回（如 SPC a2605&m2605）。
        本方法会自动将组合持仓拆分为两个单腿持仓并保存。
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询持仓失败: {pRspInfo.ErrorMsg}")
        elif pInvestorPosition and pInvestorPosition.Position > 0:
            if not self._try_save_combination_position(pInvestorPosition):
                self._save_single_position(pInvestorPosition)
        elif pInvestorPosition and pInvestorPosition.Position == 0:
            self._log_zero_position(pInvestorPosition)

        if bIsLast:
            self._finish_position_query()

    def _try_save_combination_position(self, pInvestorPosition) -> bool:
        """尝试拆分并保存组合持仓；若不是组合持仓则返回 ``False``。"""
        if not is_combination_instrument(pInvestorPosition.InstrumentID):
            return False

        legs = split_combination_position(pInvestorPosition)
        if not legs or len(legs) != 2:
            self.logger.warning(f"⚠️ 无法拆分组合持仓: {pInvestorPosition.InstrumentID}, 跳过该记录")
            return True

        self._log_combination_position_split(pInvestorPosition, legs)
        for leg in legs:
            self._save_split_leg_position(pInvestorPosition, leg)
        return True

    def _log_combination_position_split(self, pInvestorPosition, legs: list[dict[str, Any]]) -> None:
        """记录组合持仓拆分后的主信息与两条单腿明细。"""
        comb_info = get_combination_info(pInvestorPosition.InstrumentID)
        if comb_info is None:
            return

        self.logger.info(
            f"🔄 拆分组合持仓: {pInvestorPosition.InstrumentID} ({comb_info['description']}), "
            f"持仓量: {pInvestorPosition.Position}"
        )
        self.logger.debug(f"  单腿1: {legs[0]['InstrumentID']} {legs[0]['PosiDirection']} {legs[0]['Position']}手")
        self.logger.debug(f"  单腿2: {legs[1]['InstrumentID']} {legs[1]['PosiDirection']} {legs[1]['Position']}手")

    def _save_split_leg_position(self, pInvestorPosition, leg: dict[str, Any]) -> None:
        """将拆分后的单腿持仓转换为标准模型并写入缓存。"""
        leg_key = (
            f"{leg['InstrumentID']}_{leg['PosiDirection']}_{leg.get('PositionDate', pInvestorPosition.PositionDate)}"
        )
        leg_position_dict = self._build_split_leg_payload(pInvestorPosition, leg)

        try:
            position_model = CtpConverter.position_to_model(SimpleNamespace(**leg_position_dict))
            self.positions[leg_key] = position_model
            # PositionField 模型本身不含 combination_origin 字段，因此在 trader
            # 上单独维护审计映射，由 data_converter 读出后填入 UnifiedPosition.extra。
            origin = leg.get("combination_origin") or pInvestorPosition.InstrumentID
            self.combination_origins[leg["InstrumentID"]] = origin
            direction_desc = self._describe_position_direction(leg["PosiDirection"])
            self.logger.debug(f"  保存单腿持仓: {leg['InstrumentID']} {direction_desc} {leg['Position']}手")
        except Exception as e:
            self.logger.error(f"保存单腿持仓失败: {e}")

    def _build_split_leg_payload(self, pInvestorPosition, leg: dict[str, Any]) -> dict[str, Any]:
        """基于原始组合持仓构造单腿转换所需的字段字典。"""
        leg_position_dict: dict[str, Any] = {}
        if hasattr(pInvestorPosition, "__dict__"):
            for key, value in pInvestorPosition.__dict__.items():
                leg_position_dict[key] = value

        leg_position_dict["InstrumentID"] = leg["InstrumentID"]
        leg_position_dict["PosiDirection"] = leg["PosiDirection"]
        leg_position_dict["Position"] = leg["Position"]
        if "PositionDate" in leg:
            leg_position_dict["PositionDate"] = leg["PositionDate"]
        return leg_position_dict

    def _save_single_position(self, pInvestorPosition) -> None:
        """保存普通单腿持仓，并输出调试日志。"""
        key = f"{pInvestorPosition.InstrumentID}_{pInvestorPosition.PosiDirection}_{pInvestorPosition.PositionDate}"
        position_model = CtpConverter.position_to_model(pInvestorPosition)
        self.positions[key] = position_model

        direction_desc = self._describe_position_direction(pInvestorPosition.PosiDirection)
        position_date_desc = self._describe_position_date(pInvestorPosition.PositionDate)
        self.logger.debug(f"查询到持仓: {position_model.InstrumentID} {direction_desc} {position_date_desc}")
        self.logger.debug(f"  存储键: {key}")
        self.logger.debug(
            f"  持仓量: {position_model.Position}, 昨持仓: {position_model.YdPosition}, 今持仓: {position_model.TodayPosition}"
        )
        self.logger.debug(
            f"  占用保证金: {position_model.UseMargin:.2f}, 持仓盈亏: {position_model.PositionProfit:.2f}"
        )

    def _log_zero_position(self, pInvestorPosition) -> None:
        """记录被忽略的零持仓信息。"""
        key = f"{pInvestorPosition.InstrumentID}_{pInvestorPosition.PosiDirection}_{pInvestorPosition.PositionDate}"
        self.logger.debug(f"忽略零持仓记录: {key}")

    def _finish_position_query(self) -> None:
        """输出持仓查询汇总，并唤醒等待中的查询事件。"""
        self.logger.info(f"持仓查询完成，共查询到 {len(self.positions)} 个持仓记录")

        instrument_stats: dict[str, dict[str, int]] = {}
        for position in self.positions.values():
            instrument_id = position.InstrumentID
            stats = instrument_stats.setdefault(
                instrument_id,
                {"long": 0, "short": 0, "net": 0, "records": 0},
            )
            stats["records"] += 1
            self._accumulate_position_stats(stats, position)

        for stats in instrument_stats.values():
            stats["net"] = stats["long"] - stats["short"]

        for instrument_id, stats in instrument_stats.items():
            if stats["records"] > 1:
                self.logger.info(
                    f"合约 {instrument_id}: 多头{stats['long']}手, 空头{stats['short']}手, 净持仓{stats['net']}手"
                )
                continue

            direction = "多头" if stats["long"] > 0 else "空头" if stats["short"] > 0 else "平仓"
            position = stats["long"] if stats["long"] > 0 else stats["short"]
            self.logger.info(f"合约 {instrument_id}: {direction} {position}手")

        for key in list(self.query_events.keys()):
            if key.startswith("position"):
                self.query_events[key].set()

    def _accumulate_position_stats(self, stats: dict[str, int], position: PositionField) -> None:
        """将单条持仓累加到查询汇总统计中。"""
        if position.PosiDirection == "2":
            stats["long"] += position.Position
            return
        if position.PosiDirection == "3":
            stats["short"] += position.Position
            return
        if position.PosiDirection == "1":
            if position.Position > 0:
                stats["long"] += position.Position
            elif position.Position < 0:
                stats["short"] += abs(position.Position)

    def _describe_position_direction(self, posi_direction: str) -> str:
        """返回持仓方向的人类可读描述。"""
        if posi_direction == "2":
            return "多头"
        if posi_direction == "3":
            return "空头"
        return "净持仓"

    def _describe_position_date(self, position_date: str) -> str:
        """返回持仓日期维度的人类可读描述。"""
        if position_date == "1":
            return "今日持仓"
        if position_date == "2":
            return "昨日持仓"
        return f"其他日期({position_date})"

    def get_position_info(self, instrument_id: str) -> dict[str, str | int]:
        """
        获取合约的持仓信息汇总.

        Parameters
        ----------
        instrument_id : str
            合约代码。

        Returns
        -------
        dict[str, str | int]
            持仓信息汇总字典。
        """
        # 使用单独的计数器变量以避免类型问题
        long_position = 0
        long_yd_position = 0
        long_today_position = 0
        short_position = 0
        short_yd_position = 0
        short_today_position = 0

        # 遍历所有持仓记录，按方向和日期聚合
        for key, position in self.positions.items():
            if not key.startswith(instrument_id):
                continue

            # 多头持仓 (PosiDirection = '2')
            if position.PosiDirection == "2":
                long_position += position.Position
                long_yd_position += position.YdPosition
                long_today_position += position.TodayPosition

            # 空头持仓 (PosiDirection = '3')
            elif position.PosiDirection == "3":
                short_position += position.Position
                short_yd_position += position.YdPosition
                short_today_position += position.TodayPosition

            # 净持仓 (PosiDirection = '1') - 直接计算净持仓
            elif position.PosiDirection == "1":
                # 净持仓直接计入对应方向
                if position.Position > 0:  # 净多头
                    long_position += position.Position
                    long_yd_position += position.YdPosition
                    long_today_position += position.TodayPosition
                elif position.Position < 0:  # 净空头
                    short_position += abs(position.Position)
                    short_yd_position += position.YdPosition
                    short_today_position += position.TodayPosition

        # 构建返回字典
        return {
            "instrument_id": instrument_id,
            "long_position": long_position,
            "long_yd_position": long_yd_position,
            "long_today_position": long_today_position,
            "short_position": short_position,
            "short_yd_position": short_yd_position,
            "short_today_position": short_today_position,
            "net_position": long_position - short_position,
        }

    def get_positions_summary(self) -> list[dict[str, Any]]:
        """获取持仓摘要信息."""
        # 按合约ID分组聚合持仓
        self.query_positions()
        instrument_positions = {}

        for key, position in self.positions.items():
            instrument_id = position.InstrumentID

            if instrument_id not in instrument_positions:
                instrument_positions[instrument_id] = {
                    "instrument_id": instrument_id,
                    "exchange_id": position.ExchangeID,
                    "long_position": 0,
                    "short_position": 0,
                    "net_position": 0,
                    "long_yd_position": 0,
                    "short_yd_position": 0,
                    "today_position": 0,
                    "total_position_profit": 0.0,
                    "total_position_cost": 0.0,
                    "total_use_margin": 0.0,
                    "SettlementPrice": position.SettlementPrice,
                    "hedge_flag": position.HedgeFlag,
                    "details": [],  # 保留详细记录用于调试
                }

            agg = instrument_positions[instrument_id]

            # 保存详细记录
            direction_desc = (
                "多头" if position.PosiDirection == "2" else "空头" if position.PosiDirection == "3" else "净持仓"
            )
            agg["details"].append(
                {
                    "key": key,
                    "direction": direction_desc,
                    "direction_code": position.PosiDirection,
                    "position_date": position.PositionDate,
                    "position": position.Position,
                    "yd_position": position.YdPosition,
                    "today_position": position.TodayPosition,
                    "position_profit": position.PositionProfit,
                    "position_cost": position.PositionCost,
                    "use_margin": position.UseMargin,
                }
            )

            # 按方向聚合持仓
            if position.PosiDirection == "2":  # 多头
                agg["long_position"] += position.Position
                agg["long_yd_position"] += position.YdPosition
                agg["today_position"] += position.TodayPosition
            elif position.PosiDirection == "3":  # 空头
                agg["short_position"] += position.Position
                agg["short_yd_position"] += position.YdPosition
                agg["today_position"] += position.TodayPosition
            elif position.PosiDirection == "1":  # 净持仓
                if position.Position > 0:  # 净多头
                    agg["long_position"] += position.Position
                    agg["long_yd_position"] += position.YdPosition
                    agg["today_position"] += position.TodayPosition
                elif position.Position < 0:  # 净空头
                    agg["short_position"] += abs(position.Position)
                    agg["short_yd_position"] += position.YdPosition
                    agg["today_position"] += position.TodayPosition

            # 聚合计量数据
            agg["total_position_profit"] += position.PositionProfit
            agg["total_position_cost"] += position.PositionCost
            agg["total_use_margin"] += position.UseMargin

            # 计算净持仓
            agg["net_position"] = agg["long_position"] - agg["short_position"]

        # 生成摘要列表（只显示有持仓的合约）
        summary = []
        for instrument_id, agg in instrument_positions.items():
            if agg["long_position"] > 0 or agg["short_position"] > 0:
                # 把组合拆腿审计字段透传到摘要，data_converter 会写入 position.extra。
                origin = self.combination_origins.get(instrument_id)
                if origin:
                    agg["combination_origin"] = origin
                summary.append(agg)

        # 按合约代码排序
        def sort_key(x: dict[str, Any]) -> str:
            return str(x.get("instrument_id", ""))

        summary.sort(key=sort_key)

        return summary
