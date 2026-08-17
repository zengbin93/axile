# SINGLE-MAKER 算法

## 概述

单一做市商算法（回调版本）- 使用事件驱动等待，支持追单功能。

**适用渠道**: 实现统一执行器协议且支持订单回报的渠道

**算法标识**: `SINGLE-MAKER`

## 算法特点

### 事件驱动架构
- 基于 WebSocket 回调实时接收订单状态更新
- 避免轮询开销，响应更快
- 支持事件驱动的订单状态监控

### 追单功能
- 可选的价格追单机制
- 自动检测订单成交情况
- 智能调整价格以提高成交概率

### 风险控制
- 支持风险品种强制清仓
- 自动撤销未完成订单
- 完善的错误处理机制

## 执行流程

```
1. 初始化阶段
   ├─ 准备交易数据（账户资产、市场数据、目标持仓）
   ├─ 初始化 WebSocket 连接
   └─ 创建订单跟踪器并注册回调

2. 订单准备阶段
   ├─ 撤销所有未完成订单
   └─ 计算每个品种的调仓需求

3. 订单提交阶段（按品种串行）
   ├─ 检查风险品种列表
   ├─ 计算当前持仓 vs 目标持仓
   ├─ 确定交易方向和数量
   ├─ 确定订单类型和价格
   ├─ 确定 position_side（如果需要）
   └─ 提交订单到交易所

4. 订单监控阶段
   ├─ 通过回调实时更新订单状态
   ├─ 追单逻辑（如果启用）
   │  ├─ 监控价格偏离
   │  ├─ 达到阈值后撤单重下
   │  └─ 记录追单事件
   └─ 等待所有订单完成或超时

5. 清理阶段
   ├─ 注销回调函数
   ├─ 重新获取账户资产
   └─ 返回执行结果
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
        "method": "SINGLE-MAKER",
        "params": {
            "max_wait_seconds": 60,
        },
    },
    risk_symbols=set(),
    trade_rules={},
)
```

### 启用追单

```python
input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"rb2510": 2.0, "au2512": 1.0},
    last_target={},
    algorithm={
        "method": "SINGLE-MAKER",
        "params": {
            "max_wait_seconds": 120,
            "chase_enabled": True,
            "chase_ticks": 2,  # 价格偏离2跳后追单
            "max_chase_count": 3,  # 最多追3次
            "chase_interval": 3.0,  # 每3秒追一次
        },
    },
    risk_symbols=set(),
    trade_rules={},
)
```

### 带风险品种的配置

```python
input_data = UnifiedStandardInput(
    channel_type=TradeChannel.CTP,
    account_config=ctp_config,
    curr_target={"SQhc9001": 2.0, "rb2510": 2.0},
    last_target={},
    algorithm={
        "method": "SINGLE-MAKER",
        "params": {
            "max_wait_seconds": 60,
        },
    },
    risk_symbols={"rb2510"},  # rb2510 被标记为风险品种，将被强制清仓
    trade_rules={},
)
```

## 订单类型选择逻辑

算法会根据市场数据自动选择订单类型：

- **有市场数据**: 使用 `LIMIT` 限价单，价格取对手价
  - 买入：使用 `ask_price`（卖一价）
  - 卖出：使用 `bid_price`（买一价）

- **无市场数据**: 使用 `MARKET` 市价单，价格为 0

## position_side 处理

对于需要 `position_side` 参数的双向持仓渠道，算法会：

1. 检查该品种是否有对应方向的持仓
2. 如果有持仓，则设置对应的 `position_side`
3. 如果没有持仓，则不传 `position_side` 参数

## 追单机制详解

### 启用条件

```python
chase_enabled = True
```

### 追单触发条件

1. 订单状态为部分成交或未成交
2. 最新价格偏离订单价格达到 `chase_ticks` 跳
3. 距离上次追单时间超过 `chase_interval` 秒
4. 追单次数未超过 `max_chase_count`

### 追单执行流程

1. 撤销原订单
2. 重新计算价格（使用最新的对手价）
3. 提交新订单
4. 更新订单跟踪器
5. 记录追单审计事件

## 错误处理

### 可恢复错误

对于网络异常、交易所临时错误等可恢复异常：

- 记录错误日志
- 将错误信息写入 `execution_memory`
- 继续处理其他品种
- 不中断整个算法执行

### 不可恢复错误

对于 `MemoryError` 等严重错误：

- 记录异常堆栈
- 立即终止算法执行
- 向上抛出异常

## 返回结果

### AlgorithmResult 结构

```python
AlgorithmResult(
    orders=[...],                    # 所有生成的订单列表
    account_assets=...,              # 最终账户资产
    target_volume={...},             # 目标持仓字典
    market_data={...},               # 市场数据
    memory={
        "algorithm": "SINGLE-MAKER",
        "curr_target": {...},        # 当前目标持仓
        "execution_details": {       # 执行详情
            "SYMBOL_adjustment": {
                "from": 0.0,
                "to": 2.0,
                "diff": 2.0,
                "direction": "BUY",
                "volume": 2.0,
                "order_id": "12345",
            },
            ...
        },
        "symbols_processed": 2,      # 处理的品种数量
        "orders_generated": 2,       # 生成的订单数量
        "total_asset": 100000.0,     # 总资产
        "chase_enabled": False,      # 是否启用追单
    }
)
```

## 与其他算法对比

`SINGLE-MAKER` 现在就是默认的单品种执行算法。
通用执行层会按 symbol 拆分并并发调度，因此不再需要单独的 polling / concurrent 变体。

## 最佳实践

### 1. 追单配置建议

- **稳定市场**: `chase_ticks=1`, `max_chase_count=3`
- **波动市场**: `chase_ticks=2`, `max_chase_count=5`
- **极端行情**: 禁用追单 `chase_enabled=False`

### 2. 超时时间设置

- **正常情况**: `max_wait_seconds=60`
- **网络不稳定**: `max_wait_seconds=120`
- **需要快速完成**: `max_wait_seconds=30`

### 3. 风险管理

- 及时更新 `risk_symbols` 列表
- 设置合理的 `max_wait_seconds` 避免长时间挂起
- 监控执行日志，关注追单和成交情况

## 注意事项

1. **WebSocket 连接**: 算法依赖 WebSocket 连接接收实时更新，确保网络稳定

2. **回调注册**: 算法会自动注册和注销回调，无需手动管理

3. **订单跟踪**: 所有订单都由 `OrderTracker` 统一管理，确保状态一致

4. **资源清理**: 算法使用 `try-finally` 确保回调正确注销

5. **品种顺序**: 订单按品种串行提交，确保每个品种的订单完全提交后再提交下一个

## 性能指标

- **平均响应时间**: < 100ms（事件驱动）
- **订单提交延迟**: 取决于网络和交易所
- **追单响应**: < 1s（价格更新后）

## 相关模块

- `axile.executor.algorithms.utils.order_tracker.OrderTracker`: 订单跟踪器
- `axile.executor.algorithms.utils.determine_order_price`: 价格确定
- `axile.executor.algorithms.utils.determine_position_side`: position_side 确定
