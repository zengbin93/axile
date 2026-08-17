# TARGET-POS-TASK 算法

## 概述

CTP 目标持仓算法 - 专为 CTP 渠道设计，支持智能平仓、昨今仓处理、offset_priority 等特有功能。

**适用渠道**: CTP

**算法标识**: `TARGET-POS-TASK`

## 算法特点

### 智能平仓系统
- **自动判断平昨/平今**: 根据持仓情况自动选择平仓类型
- **优先级配置**: 支持"昨今"或"今昨"两种平仓顺序
- **分腿平仓**: 将大笔平仓拆分为多腿，确保成交

### CTP 特有功能
- **offset_flag 支持**: 支持开仓、平仓、平今、平昨标志
- **昨今仓分离**: 分别处理多头/空头的昨日和今日持仓
- **净持仓计算**: 基于净持仓进行调仓决策

### 价格策略
- **PASSIVE（被动）**: 使用对手价确保成交
- **ACTIVE（主动）**: 使用最新价

### 完善的审计
- 详细的日志记录
- 完整的执行追踪
- 错误处理和恢复

## 执行流程

```
1. 初始化阶段
   ├─ 获取账户资产
   ├─ 提取 CTP 持仓详情（昨仓、今仓）
   └─ 初始化 WebSocket 连接

2. 市场数据准备
   ├─ 获取所有目标品种的市场数据
   └─ 创建订单跟踪器并注册回调

3. 撤销未完成订单
   └─ 撤销所有挂起订单

4. 计算目标持仓
   └─ 调用 executor.calculate_target_volume()

5. 持仓调整（按品种串行）
   对于每个目标品种：
   ├─ 检查风险品种列表
   ├─ 获取品种交易规则
   │  ├─ price: 价格策略（PASSIVE/ACTIVE）
   │  └─ offset_priority: 平仓优先级（昨今/今昨）
   ├─ 获取当前持仓详情
   │  ├─ long_yesterday: 多头昨仓
   │  ├─ long_today: 多头今仓
   │  ├─ short_yesterday: 空头昨仓
   │  └─ short_today: 空头今仓
   ├─ 计算净持仓变化
   ├─ 执行调仓逻辑
   │  ├─ 需要增加净持仓
   │  │  ├─ 先平空头（如果有）
   │  │  │  └─ 智能平仓（昨今/今昨）
   │  │  └─ 开多头
   │  └─ 需要减少净持仓
   │     ├─ 先平多头（如果有）
   │     │  └─ 智能平仓（昨今/今昨）
   │     └─ 开空头
   └─ 添加订单到跟踪器

6. 订单监控阶段
   ├─ 通过回调实时更新订单状态
   ├─ 追单逻辑（如果启用）
   └─ 等待所有订单完成或超时

7. 清理阶段
   ├─ 注销回调函数
   ├─ 重新获取账户资产
   └─ 返回执行结果
```

## CTP 常量定义

### 买卖方向

```python
THOST_FTDC_D_Buy = "0"  # 买入
THOST_FTDC_D_Sell = "1"  # 卖出
```

### 开平标志

```python
THOST_FTDC_OF_Open = "0"  # 开仓
THOST_FTDC_OF_Close = "1"  # 平仓（通用）
THOST_FTDC_OF_CloseToday = "3"  # 平今仓
THOST_FTDC_OF_CloseYesterday = "4"  # 平昨仓
```

### 价格类型

```python
THOST_FTDC_OPT_LimitPrice = "2"  # 限价
```

## 参数配置

### 基础参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `max_wait_seconds` | `int` | `60` | 最大等待时间（秒） |

### 追单参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `chase_enabled` | `bool` | `False` | 是否启用追单 |
| `chase_ticks` | `int` | `1` | 价格偏离多少跳后追单 |
| `max_chase_count` | `int` | `5` | 单个订单最大追单次数 |
| `chase_interval` | `float` | `5.0` | 追单间隔（秒） |

### 交易规则参数（trade_rules）

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `price` | `str` | `"PASSIVE"` | 价格策略：PASSIVE/ACTIVE |
| `offset_priority` | `str` | `"昨今"` | 平仓优先级：昨今/今昨 |

## 使用示例

### 基础配置

```python
from axile.common.trade_channel import TradeChannel
from axile.executor.models.unified_input import UnifiedStandardInput

input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"SQhc9001": 2.0, "rb2510": 2.0},
    last_target={"rb2510": 0.0},
    algorithm={
        "method": "TARGET-POS-TASK",
        "params": {
            "max_wait_seconds": 60,
        },
    },
    risk_symbols=set(),
    trade_rules={
        "rb2510": {
            "price": "PASSIVE",
            "offset_priority": "昨今",
        }
    },
)
```

### 主动价格策略

```python
input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"SQhc9001": 2.0},
    last_target={},
    algorithm={
        "method": "TARGET-POS-TASK",
        "params": {
            "max_wait_seconds": 60,
        },
    },
    risk_symbols=set(),
    trade_rules={
        "SQhc9001": {
            "price": "ACTIVE",  # 使用最新价
            "offset_priority": "昨今",
        }
    },
)
```

### 今昨平仓优先级

```python
input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"rb2510": 0},  # 清仓
    last_target={"rb2510": 5},
    algorithm={
        "method": "TARGET-POS-TASK",
        "params": {
            "max_wait_seconds": 60,
        },
    },
    risk_symbols=set(),
    trade_rules={
        "rb2510": {
            "price": "PASSIVE",
            "offset_priority": "今昨",  # 先平今再平昨
        }
    },
)
```

### 启用追单

```python
input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"SQhc9001": 2.0},
    last_target={},
    algorithm={
        "method": "TARGET-POS-TASK",
        "params": {
            "max_wait_seconds": 120,
            "chase_enabled": True,
            "chase_ticks": 2,
            "max_chase_count": 3,
            "chase_interval": 5.0,
        },
    },
    risk_symbols=set(),
    trade_rules={},
)
```

## CTP 持仓数据结构

### CTPPositionDetail

```python
class CTPPositionDetail:
    """CTP 持仓详情"""

    symbol: str
    long_yesterday: int  # 多头昨仓
    long_today: int  # 多头今仓
    short_yesterday: int  # 空头昨仓
    short_today: int  # 空头今仓
    long_total: int  # 多头总持仓
    short_total: int  # 空头总持仓
    net_position: int  # 净持仓（多-空）

    @property
    def total_yesterday(self) -> int:
        """昨仓总量"""
        return long_yesterday + short_yesterday

    @property
    def total_today(self) -> int:
        """今仓总量"""
        return long_today + short_today

    @property
    def total_available_close(self) -> int:
        """可平仓总量"""
        return total_yesterday + total_today
```

## 智能平仓算法

### 平仓流程

```python
def _smart_close_position(
    executor,
    symbol,
    direction,
    close_volume,
    limit_price,
    offset_priority="昨今",
):
    """
    智能平仓算法

    流程:
    1. 获取持仓详情（昨仓、今仓）
    2. 计算可平仓数量
    3. 根据 offset_priority 确定平仓顺序
    4. 分腿提交平仓订单
    5. 如果失败，尝试通用平仓
    """
```

### 平仓顺序

**offset_priority = "昨今"**:
1. 先平昨仓（CloseYesterday）
2. 再平今仓（CloseToday）

**offset_priority = "今昨"**:
1. 先平今仓（CloseToday）
2. 再平昨仓（CloseYesterday）

### 后备机制

如果指定平仓类型失败，自动使用通用平仓（Close）:

```python
# 最后尝试通用平仓（作为后备）
if remaining_volume > 0:
    order = executor.place_order(
        symbol,
        direction,
        OrderType.LIMIT,
        remaining_volume,
        limit_price,
        offset_flag=THOST_FTDC_OF_Close,  # 通用平仓
    )
```

## 价格策略

### PASSIVE（被动）

确保成交的策略：

```python
def _calculate_order_price(market_data, symbol, price_type, direction):
    if price_type == "PASSIVE":
        if direction == "BUY":
            # 买入：使用买一价（确保成交）
            return price_data.bid_price
        else:  # SELL
            # 卖出：使用卖一价（确保成交）
            return price_data.ask_price
```

### ACTIVE（主动）

使用最新价的策略：

```python
if price_type == "ACTIVE":
    # 使用最新价
    return price_data.last_price
```

## 持仓调整逻辑

### 增加净持仓

```python
if adjust_volume > 0:  # 需要增加净持仓
    # 1. 先平空头（如果有）
    if position_detail.short_total > 0:
        close_volume = min(adjust_volume, position_detail.short_total)
        _smart_close_position(..., direction="BUY", ...)

    # 2. 再开多头
    if adjust_volume > 0:
        executor.place_order(
            symbol,
            OrderDirection.BUY,
            OrderType.LIMIT,
            adjust_volume,
            limit_price,
            offset_flag=THOST_FTDC_OF_Open,  # 开仓
        )
```

### 减少净持仓

```python
else:  # 需要减少净持仓
    adjust_volume = abs(adjust_volume)

    # 1. 先平多头（如果有）
    if position_detail.long_total > 0:
        close_volume = min(adjust_volume, position_detail.long_total)
        _smart_close_position(..., direction="SELL", ...)

    # 2. 再开空头
    if adjust_volume > 0:
        executor.place_order(
            symbol,
            OrderDirection.SELL,
            OrderType.LIMIT,
            adjust_volume,
            limit_price,
            offset_flag=THOST_FTDC_OF_Open,  # 开仓
        )
```

## 返回结果

### AlgorithmResult 结构

```python
AlgorithmResult(
    orders=[...],  # 所有生成的订单列表
    account_assets=...,  # 最终账户资产
    target_volume={...},  # 目标持仓字典
    market_data={...},  # 市场数据
    memory={
        "algorithm": "TARGET-POS-TASK",
        "symbols_processed": 2,  # 处理的品种数量
        "orders_generated": 5,  # 生成的订单数量
        "execution_details": {  # 执行详情
            "SQhc9001_adjustment": {
                "current_net": 0,
                "target_volume": 2,
                "orders_generated": 1,
                "price_type": "PASSIVE",
                "offset_priority": "昨今",
            },
            "rb2510_adjustment": {
                "current_net": 0,
                "target_volume": 2,
                "orders_generated": 4,
                "price_type": "PASSIVE",
                "offset_priority": "昨今",
            },
        },
        "total_asset_before": 100000.0,
        "total_asset_after": 100500.0,
        "chase_enabled": False,
    },
)
```

## 日志输出示例

```
🚀 开始TARGET-POS-TASK算法执行
📋 算法配置: UnifiedStandardInput(...)
💰 账户总资产: 100000.00, 可用资金: 50000.00
📊 获取到 2 个品种的市场数据
🔄 撤销所有未完成订单...
✅ 订单撤销完成
🎯 目标持仓数量: {'SQhc9001': 2.0, 'rb2510': 2.0}

📈 SQhc9001: 目标=2, 价格策略=PASSIVE, 平仓优先级=昨今
SQhc9001: 当前净持仓=0, 目标=2, 调整=2, 价格=4500.0, 策略=PASSIVE
📈 开多仓: SQhc9001 2手@4500.0, 订单ID: 12345

📈 rb2510: 目标=2, 价格策略=PASSIVE, 平仓优先级=昨今
rb2510: 当前净持仓=0, 目标=2, 调整=2, 价格=3800.0, 策略=PASSIVE
📈 开多仓: rb2510 2手@3800.0, 订单ID: 12346

⏳ 等待 2 个订单完成...
✅ TARGET-POS-TASK算法执行完成
```

## 错误处理

### 可恢复错误

```python
# 单腿平仓失败，继续下一腿
except Exception as e:
    logger.warning(f"平昨失败: {e}")
    # 继续尝试平今
```

### 不可恢复错误

```python
# 整个算法失败
except Exception as e:
    error_msg = f"TARGET-POS-TASK算法执行失败: {e}"
    logger.error(f"❌ {error_msg}")
    # 返回部分结果
```

## 最佳实践

### 1. offset_priority 选择

```python
# 通常情况：先平昨再平今
offset_priority = "昨今"

# 今仓手续费更低时：先平今再平昨
offset_priority = "今昨"

# 接近交割日：优先平今仓
offset_priority = "今昨"
```

### 2. price_strategy 选择

```python
# 需要确保成交
price = "PASSIVE"

# 追求更好的价格
price = "ACTIVE"

# 混合使用
trade_rules = {
    "liquid_symbol": {"price": "PASSIVE"},  # 确保成交
    "illiquid_symbol": {"price": "ACTIVE"},  # 追求价格
}
```

### 3. 超时设置

```python
# 正常情况
max_wait_seconds = 60

# 持仓较多
max_wait_seconds = 120

# 需要快速完成
max_wait_seconds = 30
```

## 注意事项

1. **CTP 特有**: 本算法仅适用于 CTP 渠道

2. **昨今仓**: CTP 的昨今仓机制需要特别注意

3. **offset_priority**: 根据手续费和交割日合理设置

4. **净持仓**: 算法基于净持仓进行调仓

5. **持仓详情**: 确保 `extra` 字段包含正确的昨今仓信息

## 适用场景

### 推荐使用

1. **CTP 渠道**: 期货交易所的 CTP 接口
2. **昨今仓管理**: 需要区分昨今仓的场景
3. **智能平仓**: 需要自动选择平昨/平今
4. **净持仓调仓**: 基于净持仓的调仓策略

### 不推荐使用

1. **其他渠道**: 非 CTP 渠道请使用其他算法
2. **简单调仓**: 不需要昨今仓区分的场景

## 性能指标

- **平均响应时间**: < 200ms
- **智能平仓**: 2-4 个订单（取决于昨今仓分布）
- **订单成交**: 取决于市场流动性

## 相关模块

- `axile.executor.algorithms.utils.order_tracker.OrderTracker`: 订单跟踪器
- `axile.executor.algorithms.utils.order_tracker.ChaseConfig`: 追单配置
- `axile.executor.models.unified_account_assets.UnifiedAccountAssets`: 统一账户资产
