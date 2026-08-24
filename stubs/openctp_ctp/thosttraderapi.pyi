from typing import Any, overload

THOST_TERT_QUICK: int
THOST_FTDC_HF_Speculation: str
THOST_FTDC_D_Buy: str
THOST_FTDC_D_Sell: str
THOST_FTDC_OF_Open: str
THOST_FTDC_OF_Close: str
THOST_FTDC_OF_CloseToday: str
THOST_FTDC_OF_CloseYesterday: str
THOST_FTDC_OPT_LimitPrice: str
THOST_FTDC_TC_GFD: str
THOST_FTDC_VC_AV: str
THOST_FTDC_FCC_NotForceClose: str
THOST_FTDC_CC_Immediately: str
THOST_FTDC_AF_Delete: str


class CThostFtdcTraderSpi: ...


class CThostFtdcReqAuthenticateField: ...


class CThostFtdcReqUserLoginField: ...


class CThostFtdcUserSystemInfoField: ...


class CThostFtdcSettlementInfoConfirmField: ...


class CThostFtdcInputOrderField: ...


class CThostFtdcInputOrderActionField: ...


class CThostFtdcQryInstrumentField: ...


class CThostFtdcQryTradingAccountField: ...


class CThostFtdcQryInvestorPositionField: ...


class CThostFtdcQryOrderField: ...


class CThostFtdcQryTradeField: ...


class CThostFtdcQrySettlementInfoField: ...


class CThostFtdcTraderApi:
    @staticmethod
    def CreateFtdcTraderApi(
        psFlowPath: str | None = None,
    ) -> "CThostFtdcTraderApi": ...

    def RegisterSpi(self, pSpi: object) -> None: ...
    def RegisterFront(self, pszFrontAddress: str) -> None: ...
    def SubscribePrivateTopic(self, nResumeType: int) -> None: ...
    def SubscribePublicTopic(self, nResumeType: int) -> None: ...
    def Init(self) -> int: ...
    def Join(self) -> int: ...
    def Release(self) -> None: ...
    def ReqAuthenticate(
        self,
        pReqAuthenticateField: CThostFtdcReqAuthenticateField,
        nRequestID: int,
    ) -> int: ...
    @overload
    def ReqUserLogin(
        self,
        pReqUserLoginField: CThostFtdcReqUserLoginField,
        nRequestID: int,
    ) -> int: ...
    @overload
    def ReqUserLogin(
        self,
        pReqUserLoginField: CThostFtdcReqUserLoginField,
        nRequestID: int,
        length: int,
        systemInfo: str,
    ) -> int: ...
    def SubmitUserSystemInfo(
        self,
        pUserSystemInfoField: CThostFtdcUserSystemInfoField,
        nRequestID: int,
    ) -> int: ...
    def ReqSettlementInfoConfirm(
        self,
        pSettlementInfoConfirm: CThostFtdcSettlementInfoConfirmField,
        nRequestID: int,
    ) -> int: ...
    def ReqQryInstrument(
        self,
        pQryInstrument: CThostFtdcQryInstrumentField,
        nRequestID: int,
    ) -> int: ...
    def ReqQryTradingAccount(
        self,
        pQryTradingAccount: CThostFtdcQryTradingAccountField,
        nRequestID: int,
    ) -> int: ...
    def ReqQryInvestorPosition(
        self,
        pQryInvestorPosition: CThostFtdcQryInvestorPositionField,
        nRequestID: int,
    ) -> int: ...
    def ReqQryOrder(
        self,
        pQryOrder: CThostFtdcQryOrderField,
        nRequestID: int,
    ) -> int: ...
    def ReqQryTrade(
        self,
        pQryTrade: CThostFtdcQryTradeField,
        nRequestID: int,
    ) -> int: ...
    def ReqQrySettlementInfo(
        self,
        pQrySettlementInfo: CThostFtdcQrySettlementInfoField,
        nRequestID: int,
    ) -> int: ...
    def ReqOrderInsert(
        self,
        pInputOrder: CThostFtdcInputOrderField,
        nRequestID: int,
    ) -> int: ...
    def ReqOrderAction(
        self,
        pInputOrderAction: CThostFtdcInputOrderActionField,
        nRequestID: int,
    ) -> int: ...


def __getattr__(name: str) -> Any: ...
