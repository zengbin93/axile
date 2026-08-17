"""``CtpTrader`` 合约查询与主力合约映射 mixin."""

# Mixin 共享属性（self.logger / self.instruments / self.api / self.query_events 等）
# 由 _main.py 的 __init__ 初始化，pyright 无法静态推断；用文件级
# reportAttributeAccessIssue 抑制这一类告警。
# 另外 handle_ctp_error 装饰器签名为 (object, **P) -> R，被装饰的 mixin 方法
# 会触发 reportArgumentType（self 不是 object），故一并抑制。
# pyright: reportAttributeAccessIssue=false
# pyright: reportArgumentType=false

from __future__ import annotations

import threading

from axile.executor.account_control.decorators import controlled_operation
from axile.executor.ctp.core.error_handler import handle_ctp_error
from axile.executor.ctp.core.objects import CtpConverter, InstrumentField
from axile.executor.ctp.core.openctp_compat import CThostFtdcQryInstrumentField
from axile.executor.ctp.core.trader._constants import CTP_TD_GLOBAL_GROUP, _wait_or_raise


class InstrumentsMixin:
    """合约查询、主力合约缓存与合约过滤."""

    def _should_keep_instrument(self, instrument: InstrumentField, *, include_options: bool = False) -> bool:
        """
        判断是否应该保留该合约.

        Parameters
        ----------
        instrument : InstrumentField
            CTP 合约对象。
        include_options : bool, default=False
            是否保留期权合约（``ProductClass == "2"``）。
            常规 ``query_instruments`` 入口默认为 ``False``，把期权过滤掉；
            ``query_option_instruments`` 入口会传 ``True``，让期权能进入
            ``self.instruments`` 供后续 ``option_action()`` 使用。

        Returns
        -------
        bool
            需要保留时返回 ``True``，否则返回 ``False``。
        """
        # 1. 检查合约状态 - 只保留交易中的合约
        instrument_status = getattr(instrument, "InstrumentStatus", None)
        if instrument_status is not None:
            # 常见的交易状态值
            trading_status = ["1", "2", "3"]  # 通常1=上市、2=交易、3=连续交易
            if instrument_status not in trading_status:
                return False

        # 2. 检查是否是期权合约 - 默认过滤期权；通过 include_options 开关放行
        if hasattr(instrument, "ProductClass"):
            # ProductClass: 1=期货, 2=期权, 3=组合, 4=即期, 5=ETF, 6=股票
            if not include_options and instrument.ProductClass == "2":  # 期权
                return False

        # 4. 检查合约是否已过期
        if hasattr(instrument, "ExpireDate"):
            from datetime import date, datetime

            try:
                # ExpireDate格式通常是YYYYMMDD
                expire_date = datetime.strptime(instrument.ExpireDate, "%Y%m%d").date()
                today = date.today()
                if expire_date < today:
                    return False
            except (ValueError, TypeError):
                # 如果日期解析失败，保留合约
                pass

        # 5. 检查是否是测试合约（通常以T开头）
        if hasattr(instrument, "InstrumentID"):
            instrument_id = instrument.InstrumentID
            if instrument_id.startswith("T"):
                return False

        return True

    @controlled_operation(
        "query_instruments",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    @handle_ctp_error
    def query_instruments(
        self,
        exchange_id: str = "",
        product_id: str = "",
        instrument_id: str = "",
        timeout: float = 120.0,
    ) -> dict[str, InstrumentField]:
        """查询合约.

        接口文档 https://documentation.help/CTP-API-cn/REQQRYINSTRUMENT.html

        Parameters
        ----------
        exchange_id : str, default=""
            交易所代码。
        product_id : str, default=""
            产品代码。
        instrument_id : str, default=""
            合约代码。
        timeout : float, default=120.0
            查询超时时间，单位为秒。
        """
        is_valid, error_msg = self._check_operation_frequency("query")
        if not is_valid:
            self.logger.error(f"🚫 风控拒绝查询：{error_msg}")
            raise ValueError(f"查询频率超限：{error_msg}")

        # 记录操作
        self._record_operation("query")
        req = CThostFtdcQryInstrumentField()
        req.ExchangeID = exchange_id
        req.ProductID = product_id
        req.InstrumentID = instrument_id

        event_key = f"instrument_{exchange_id}_{product_id}_{instrument_id}"
        self.query_events[event_key] = threading.Event()
        self.api.ReqQryInstrument(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            timeout,
            "查询合约超时",
            stop_event=self.stop_event,
        )
        return self.instruments

    @controlled_operation(
        "query_option_instruments",
        groups=(CTP_TD_GLOBAL_GROUP,),
        success_outcome="fetched",
    )
    @handle_ctp_error
    def query_option_instruments(
        self,
        exchange_id: str = "",
        underlying_instrument_id: str = "",
        instrument_id: str = "",
        timeout: float = 120.0,
    ) -> dict[str, InstrumentField]:
        """查询期权合约（绕过 ``_should_keep_instrument`` 的期权过滤）.

        Parameters
        ----------
        exchange_id : str, default=""
            交易所代码。
        underlying_instrument_id : str, default=""
            标的合约代码（如 ``m2510``）；优先按标的过滤再按合约过滤。
            注：CTP 标准 ``ReqQryInstrument`` 不直接支持按标的过滤，
            因此当前实现只在回调写入 ``self.instruments`` 时按 underlying
            过滤返回值。
        instrument_id : str, default=""
            期权合约代码（如 ``m2510-C-3000``）；与 ``underlying_instrument_id`` 二选一即可。
        timeout : float, default=120.0
            查询超时秒数。

        Returns
        -------
        dict[str, InstrumentField]
            本次查询匹配到的期权合约子集；同时会合并到 ``self.instruments``。

        Notes
        -----
        - 期权合约会写入 ``self.instruments``；后续 ``option_action()`` /
          ``submit_option_action()`` 会从这里读取。
        - 与 ``query_instruments`` 共用 ``OnRspQryInstrument`` 回调，
          通过 ``self._option_query_event_keys`` 标记当前批次允许期权写入。
        """
        is_valid, error_msg = self._check_operation_frequency("query")
        if not is_valid:
            self.logger.error(f"🚫 风控拒绝查询：{error_msg}")
            raise ValueError(f"查询频率超限：{error_msg}")

        self._record_operation("query")
        req = CThostFtdcQryInstrumentField()
        req.ExchangeID = exchange_id
        req.InstrumentID = instrument_id
        # underlying_instrument_id 不直接传给 CTP，留作回调后过滤的依据

        event_key = f"option_instrument_{exchange_id}_{underlying_instrument_id}_{instrument_id}"
        self.query_events[event_key] = threading.Event()
        # 标记当前批次：让 OnRspQryInstrument 在期权过滤时走 include_options=True
        self._option_query_event_keys.add(event_key)
        self.api.ReqQryInstrument(req, 0)

        _wait_or_raise(
            self.query_events[event_key],
            timeout,
            "查询期权合约超时",
            stop_event=self.stop_event,
        )

        # 返回本次查询命中的期权子集
        if underlying_instrument_id:
            return {
                k: v
                for k, v in self.instruments.items()
                if v.ProductClass == "2" and getattr(v, "UnderlyingInstrID", "") == underlying_instrument_id
            }
        if instrument_id:
            return {k: v for k, v in self.instruments.items() if k == instrument_id and v.ProductClass == "2"}
        return {k: v for k, v in self.instruments.items() if v.ProductClass == "2"}

    def OnRspQryInstrument(self, pInstrument, pRspInfo, _nRequestID, bIsLast):
        """查询合约响应."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.logger.error(f"查询合约失败: {pRspInfo.ErrorMsg}")
            # 不要直接return，继续处理bIsLast
        elif pInstrument:
            instrument_id = pInstrument.InstrumentID

            # 合约过滤：当存在 option_instrument_* 查询事件时放宽期权过滤
            include_options = bool(getattr(self, "_option_query_event_keys", set()))
            if self._should_keep_instrument(pInstrument, include_options=include_options):
                # 转换为Pydantic模型
                instrument_model = CtpConverter.instrument_to_model(pInstrument)
                self.instruments[instrument_id] = instrument_model

        if bIsLast:
            self.logger.info(f"合约查询完成，共查询到 {len(self.instruments)} 个合约")
            # 触发所有相关的查询事件并清理 option 查询标记
            for key in list(self.query_events.keys()):
                if key.startswith(("instrument", "option_instrument")):
                    self.query_events[key].set()
                    self._option_query_event_keys.discard(key)

    def get_main_contract(self, symbol: str) -> str:
        """获取品种对应的主力合约.

        采用交易所信息缓存机制，在实例中保存主力合约映射，
        避免重复查询外部API，提高性能。

        Parameters
        ----------
        symbol : str
            品种代码，例如 ``"rb"``、``"SQhc9001"`` 等。

        Returns
        -------
        str
            对应的具体合约代码；如果无法找到主力合约，则返回原始 ``symbol``。
        """
        from axile.executor.ctp.utils.main_contracts import init_futures_main_contracts

        # 懒加载：只在第一次使用时初始化主力合约映射
        if not self.main_contracts:
            try:
                self.main_contracts = init_futures_main_contracts()
                self.logger.debug(f"已缓存 {len(self.main_contracts)} 个主力合约映射")
            except (OSError, RuntimeError, ValueError) as e:
                self.logger.warning(f"获取主力合约映射失败: {e}，将使用原始symbol")
                return symbol

        # 处理9001后缀的品种代码（如 SQhc9001）
        if symbol.endswith("9001"):
            # 提取品种代码，去掉交易所前缀和9001后缀
            # 例如: SQhc9001 -> hchc
            variety = symbol[2:-4]
            contract = self.main_contracts.get(variety, symbol)
            # 添加交易所前缀
            return f"{symbol[:2]}{contract}"
        elif symbol in self.main_contracts:
            return self.main_contracts[symbol]
        else:
            # 如果不是品种代码也不是9001格式，直接返回
            return symbol
