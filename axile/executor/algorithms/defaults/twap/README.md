# TWAP（时间加权平均价格）

将一次调仓在给定时间窗口内**均匀切成若干片**逐片下单，降低单笔大额订单的市场冲击，
使成交均价贴近区间时间加权价格。适用于所有实现统一执行器协议的渠道。

## 算法语义

- **目标为净持仓**：算法先把 `target_volume` 转成相对当前持仓的增量 `delta = target − current`，
  再对 `delta` 做时间切片，因此表达的是“调仓到位”而非“买入 N 手”。`delta == 0` 时直接返回空结果。
- **累计进度表切片**：第 `i` 片下单量 = “到该片结束应累计完成的量” − “已成交量”。
  该策略同时实现：
  1. **等距推进**——正常情况下每片量相等；
  2. **carry-over 追平**——某片欠量（限价未成交/被拒）自动滚入后续片；
  3. **残差归尾片**——取整误差与前序欠量由最后一片一次吃掉，确保收敛到目标。
- **不在算法层取整**：下单量直接交给各渠道执行器按 lot / 最小下单量兜底，取整误差被进度表自动吸收。
- **可协作终止**：每个切片边界响应 `terminate` 请求。
- **片间等待走统一时钟**：仿真环境下自动加速，无需真实等待。

## 参数

| 参数 | 类型 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- | --- |
| `total_duration` | int | 300 | 1–86400 | 总执行时长（秒） |
| `slices` | int | 10 | 1–1000 | 均匀切片数，间隔 = `total_duration / slices` |
| `price_strategy` | str | `ACTIVE` | `ACTIVE` / `PASSIVE` | 单片报价策略 |
| `max_wait_seconds` | int | 60 | 1–3600 | 单片等待成交上限（继承自基类） |

- `ACTIVE`：取对手价（marketable），保证成交，教科书式 TWAP 的标准打法。
- `PASSIVE`：取本方价挂单，滑点更小但可能欠量，更依赖后续片追平。
- 约束：单片间隔 `total_duration / slices` 不得小于 0.1 秒（防止触发交易所限频）。

## 使用示例

```python
from axile.executor.models.unified_input import UnifiedStandardInput

standard_input = UnifiedStandardInput(
    channel_type=...,
    account_config=...,
    curr_target={"BTCUSDT": 0.03},  # 目标权重（各渠道语义见 sizing_mode）
    algorithm={
        "method": "TWAP",
        "params": {
            "total_duration": 300,  # 5 分钟
            "slices": 10,  # 切 10 片，每 30 秒一片
            "price_strategy": "ACTIVE",
        },
    },
)

output = executor.execute(standard_input)
```
