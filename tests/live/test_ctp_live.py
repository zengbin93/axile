"""CTP 联机测试 - 需要真实 CTP 环境.

本文件包含需要真实 CTP SimNow 环境的联机测试。
这些测试不是单元测试，而是在真实交易环境中验证功能。

⚠️ 环境要求：
1. 真实的 CTP SimNow 环境
2. openctp_ctp 依赖包
3. 凭据配置：在 ``tests/live.config.toml`` 的 ``[ctp]`` 段填写
   host / md_front / broker / account / password / appid / authcode
   （见 ``tests/live.config.example.toml``；亦可用同名环境变量 ``CTP_HOST`` 等覆盖）

🔧 运行方式：
   export RUN_LIVE_CTP_TESTS=1
   pytest tests/live/test_ctp_live.py

📋 测试内容：
- test_execute(): 测试目标仓位任务执行
- test_execute_single_maker(): 测试单一做市商算法
- test_empty_positions(): 测试清仓功能
- test_market_data(): 测试行情数据获取
- test_direct_client_usage(): 测试客户端直接使用

默认情况下，这些测试会被跳过，除非显式设置 RUN_LIVE_CTP_TESTS=1。
"""

import os
import sys

import pytest

from axile.common.trade_channel import TradeChannel
from axile.executor.ctp.core.trader import CtpTrader
from axile.executor.ctp.ctp_execute import CTPExecutor
from axile.executor.models.unified_input import CTPAccountConfig, UnifiedStandardInput
from tests.live_env import require_live_config

sys.path.insert(0, ".")


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_CTP_TESTS", "0") != "1",
    reason="需要真实 CTP 联机环境和依赖，默认跳过；设置 RUN_LIVE_CTP_TESTS=1 后执行",
)


CTP_REQUIRED_KEYS = ["host", "md_front", "broker", "account", "password", "appid", "authcode"]


def _load_ctp_context() -> CTPAccountConfig:
    account_env = require_live_config("RUN_LIVE_CTP_TESTS", "ctp", CTP_REQUIRED_KEYS)
    pytest.importorskip("openctp_ctp")

    return CTPAccountConfig.model_validate(
        {
            "td_front": account_env["host"],
            "md_front": account_env["md_front"],
            "broker_id": account_env["broker"],
            "investor_id": account_env["account"],
            "password": account_env["password"],
            "app_id": account_env["appid"],
            "auth_code": account_env["authcode"],
        }
    )


def _execute(standard_input: UnifiedStandardInput):
    executor = CTPExecutor(TradeChannel.CTP, standard_input.account_config)
    return executor.execute(standard_input)


def _empty_positions(account_config: CTPAccountConfig):
    executor = CTPExecutor(TradeChannel.CTP, account_config)
    return executor.empty_positions(algorithm={"method": "TARGET-POS-TASK", "params": {}})


def test_execute() -> None:
    """测试新的CTP库结构."""
    account_config = _load_ctp_context()
    # symbol = "rb2510"
    symbol = "SQrb9001"
    standard_input = UnifiedStandardInput.from_dict(
        {
            "curr_target": {
                symbol: 4.0,
            },
            "last_target": {
                symbol: 0.0,
            },
            "account_config": account_config,
            "algorithm": {
                "method": "TARGET-POS-TASK",
                "params": {},
            },
            "trade_rules": {
                symbol: {
                    "price": "PASSIVE",
                    "offset_priority": "今昨,开",
                },
            },
            "forbidden_symbols": [],
            "risk_symbols": [],
            "feishu_key": "97ef04e5-1dea-499e-a99f-58ec30b05283",
            "execution_timeout": 60,  # 执行超时时间
        }
    )

    _ = _execute(standard_input)


def test_execute_single_maker() -> None:
    """测试新的CTP库结构."""
    account_config = _load_ctp_context()
    # symbol = "rb2510"
    symbol = "SQrb9001"
    standard_input = UnifiedStandardInput.from_dict(
        {
            "curr_target": {
                symbol: 0.02,
            },
            "last_target": {
                symbol: 0.0,
            },
            "account_config": account_config,
            "algorithm": {
                # "method": "SINGLE-MAKER",
                # "params": {
                #     "max_wait_seconds": 60,
                # }
                "method": "SINGLE-MAKER",
                "params": {
                    "max_wait_seconds": 15,
                    "max_concurrency": 3,  # 最多3个订单并发提交
                },
            },
            "trade_rules": {
                symbol: {
                    "price": "PASSIVE",
                    "offset_priority": "今昨,开",
                },
            },
            "forbidden_symbols": [],
            "risk_symbols": [],
            "feishu_key": "97ef04e5-1dea-499e-a99f-58ec30b05283",
            "execution_timeout": 60,  # 执行超时时间
        }
    )

    _ = _execute(standard_input)


def test_empty_positions() -> None:
    """测试清仓功能."""
    account_config = _load_ctp_context()
    _ = _empty_positions(account_config)


def test_market_data() -> None:
    """Exercise market data and direct trader queries against a live CTP setup."""
    account_config = _load_ctp_context()
    # 1. 创建集成的交易客户端（包含行情功能）
    trader = CtpTrader(
        host=account_config.td_front or "",
        broker=account_config.broker_id,
        user=account_config.investor_id,
        password=account_config.password,
        appid=account_config.app_id or "",
        authcode=account_config.auth_code or "",
        md_front=account_config.md_front,  # 传入行情前置地址
    )

    try:
        trader.connect()
        trader.login()

        # quote = trader.get_quote("j2509")

        # # 3. 连接行情客户端
        # success = trader.connect_market_data()
        # if not success:
        #     print("❌ 行情客户端连接失败")
        #     return

        # # 4. 订阅行情
        # test_symbols = ["j2509", "rb2509", "au2412", "i2509"]
        # print(f"📤 订阅行情: {test_symbols}")
        # trader.subscribe_market_data(test_symbols)

        info = trader.query_instruments(instrument_id="rb2509")
        print(info)

        # account = trader.query_account()
        # print(account)
        # # 5. 等待行情数据
        # print("⏳ 等待行情数据...")
        # time.sleep(5)

        # 6. 展示各种行情获取方法
        print("\n📊 行情数据获取演示:")
        print("-" * 30)

        # for symbol in test_symbols:
        #     # 方法1：直接获取行情对象
        #     quote = trader.get_quote(symbol)
        #     if quote:
        #         print(f"✅ {symbol}: {quote.LastPrice} @{quote.UpdateTime}")

        #         # 方法2：获取行情摘要
        #         summary = trader.get_quote_summary(symbol)
        #         if summary:
        #             print(f"   📋 摘要: 涨跌={summary['change']:+.2f} ({summary['change_pct']:+.2f}%)")
        #     else:
        #         print(f"❌ {symbol}: 无行情数据")

        # 7. 展示自动订阅功能
        print("\n🔄 测试自动订阅功能:")
        new_symbol = "m2509"  # 豆粕
        print(f"确保 {new_symbol} 行情可用...")

        available = trader.ensure_quote_available(new_symbol, auto_subscribe=True)
        if available:
            quote = trader.get_quote(new_symbol)
            if quote is not None:
                print(f"✅ {new_symbol}: {quote.LastPrice}")
            else:
                print(f"❌ {new_symbol}: 获取行情失败")
        else:
            print(f"❌ {new_symbol}: 自动订阅失败")

        # 8. 展示行情状态
        print("\n📈 行情客户端状态:")
        trader.log_market_data_status()

        # 9. 获取所有行情数据
        all_quotes = trader.get_all_quotes()
        print(f"\n📊 当前共有 {len(all_quotes)} 个合约的行情数据")

        # 10. 演示在交易中使用行情数据
        print("\n💼 交易中使用行情演示:")
        demo_symbol = "j2509"
        quote = trader.get_quote(demo_symbol)

        if quote:
            print(f"准备交易 {demo_symbol}:")
            print(f"  当前价格: {quote.LastPrice}")
            print(f"  买一价: {quote.BidPrice1} x {quote.BidVolume1}")
            print(f"  卖一价: {quote.AskPrice1} x {quote.AskVolume1}")

            # 可以基于行情数据进行交易决策
            # 这里仅作演示，不实际下单
            print("  💡 可基于行情数据进行智能定价和风控")

        # 11. 风控和行情结合使用
        print("\n🛡️  风控和行情结合演示:")
        trader.log_risk_status()

        print("🎯 演示完成！")

    except Exception as e:
        pytest.fail(f"演示过程中出错: {e}")

    finally:
        # 清理资源
        trader.close()
        print("🧹 资源清理完成")


def test_direct_client_usage() -> None:
    """测试直接使用客户端."""
    account_config = _load_ctp_context()
    # 交易客户端示例
    trader = CtpTrader(
        host=account_config.td_front or "",
        broker=account_config.broker_id,
        user=account_config.investor_id,
        password=account_config.password,
        appid=account_config.app_id or "",
        authcode=account_config.auth_code or "",
        verbose=True,  # 启用详细日志
    )

    try:
        # 连接和登录
        trader.connect()
        trader.login()

        # 查询账户
        account = trader.query_account()
        assert account is not None
        print(f"可用资金: {account.Available}")

        # 查询持仓
        positions = trader.query_positions()
        print(f"持仓数量: {len(positions)}")

        _ = trader.query_instruments(instrument_id="j2511")
        # _ = trader.query_instruments(exchange_id="SHFE")
    except Exception as e:
        pytest.fail(f"客户端使用失败: {e}")
    finally:
        trader.close()


if __name__ == "__main__":
    # test_execute()
    # test_market_data()
    test_empty_positions()
    # test_direct_client_usage()
    # test_cancel_all_orders()
