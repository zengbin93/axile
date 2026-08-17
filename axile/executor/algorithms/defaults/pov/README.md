# POV（Percentage of Volume，参与率）

按**市场实时成交量**的固定比例跟单：市场成交活跃时多下、清淡时少下，使自身始终只占
市场成交的一小部分，从而降低冲击成本、隐蔽大单。全渠道通用（数据前提见下）。

## 算法语义

- **目标为净持仓**：先把 `target_volume` 转成相对当前持仓的增量 `delta = target − current`，
  再对 `delta` 按市场量参与。`delta == 0` 时直接返回空结果。
- **累计跟踪**：目标累计成交 = `参与率 × 已见市场量`，本轮下单量 = 该目标 − 已成交量，
  以「距目标剩余量」封顶。与 TWAP 的累计进度表同思想——天然追平欠量，且不超过整体目标。
- **市场成交量来源**：注册价格回调，累加每次行情更新携带的**增量成交量**
  （`UnifiedPriceData.volume`）。
- **无量安全**：市场无量则不下单，跑到 `max_duration` 上限；`complete_on_timeout` 为真时
  到期补齐剩余量，兑现「调仓到位」契约（与 TWAP 一致）。
- **不在算法层取整**：下单量交由各渠道执行器按 lot / 最小下单量兜底。
- **可协作终止**：每个轮询边界响应 `terminate`。

## 数据前提（重要）

POV 依赖「能看见市场实时成交量」。各渠道 `UnifiedPriceData.volume` 的可用性：

| 环境 | 成交量 | 说明 |
| --- | --- | --- |
| 仿真 | ✅ 逐 tick 增量 | `DataGenerator` 每 tick 带量 |
| 支持增量成交量的渠道插件 | ✅ 逐笔增量 | 插件通过统一价格回调注入 |
| CTP | ⚠️ 日内累计 | 语义为累计量，需按「做差」适配，暂不在本实现范围 |

本实现把价格回调的 `volume` 当作**增量**累加；累计型渠道（CTP）接入前 POV 不应直接用于该渠道。

## 参数

| 参数 | 类型 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- | --- |
| `participation_rate` | float | 0.1 | (0, 1] | 目标市场成交量参与比例 |
| `interval_seconds` | float | 5.0 | ≥0.1 | 轮询/下单节奏（秒） |
| `max_duration` | int | 600 | 1–86400，且 ≥ interval | 硬时间上限（秒） |
| `price_strategy` | str | `ACTIVE` | ACTIVE / PASSIVE | 单片报价策略 |
| `complete_on_timeout` | bool | `True` | — | 到期是否补齐剩余量到目标 |

- `ACTIVE`：取对手价（marketable），跟量成交更确定；`PASSIVE`：取本方价，滑点更小但可能欠量。

## 使用示例

```python
from axile.executor.models.unified_input import UnifiedStandardInput

standard_input = UnifiedStandardInput(
    channel_type=...,
    account_config=...,
    curr_target={"BTCUSDT": 0.03},  # 目标权重（各渠道语义见 sizing_mode）
    algorithm={
        "method": "POV",
        "params": {
            "participation_rate": 0.1,  # 参与 10% 的市场成交量
            "interval_seconds": 5,
            "max_duration": 600,
            "price_strategy": "ACTIVE",
            "complete_on_timeout": True,
        },
    },
)

output = executor.execute(standard_input)
```

## 已知简化

- 若渠道行情载荷包含我方自身成交，参与率基数会被自身成交量轻微抬高（上界即参与率本身）；
  标准 POV 首版接受该误差，暂不剔除。
