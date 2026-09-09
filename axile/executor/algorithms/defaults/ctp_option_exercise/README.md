# CTP_OPTION_EXERCISE · CTP 期权行权

提交期权行权、放弃或自对冲指令，并等待状态回报。按指定张数执行，不用于账户主交易或清仓。

## 执行方式

仅用于 CTP 单品种期权指令。`target_volume` 表示行权、放弃或自对冲张数，
不是交易完成后的净持仓。调用方应提供非负整数张数；非正目标跳过。

通过 `symbol_algorithms` 配置，不可设为账户主交易或清仓算法（注册元数据 `slots=[]`）。
默认行权前检查内在价值，无内在价值时跳过；该检查不是包含费用、资金等因素的完整收益评估。

## 参数

| 参数 | 默认值 | 约束 | 说明 |
|---|---|---|---|
| `action` | `"exercise"` | 见说明 | 行权、放弃或自对冲；按指定张数执行。 |
| `require_value_check` | `true` | 见说明 | 仅行权时生效；关闭后跳过内在价值检查，不代表完整收益评估。 |
| `poll_interval_seconds` | `0.5` | 见说明 | 查询指令状态的间隔。 |
| `max_wait_seconds` | `60` | ≥1，≤3600 | 等待指令终态的上限；等待结束不等于指令完成。 |

## 例子

```python
symbol_algorithms = {
    "m2510-C-3000": {
        "method": "CTP_OPTION_EXERCISE",
        "params": {
            "action": "exercise",
            "require_value_check": True,
            "poll_interval_seconds": 0.5,
            "max_wait_seconds": 60,
        },
    },
}
curr_target = {"m2510-C-3000": 5}
trade_rules = {"m2510-C-3000": {"sizing_mode": "lots"}}
```

这是单品种调用配置片段；合约代码仅作示例。目标是提交 5 张指令，不是把持仓调到 5 张。

## 结束与指令状态

提交后轮询指令状态。`executed`、`abandoned` 视为成功；`cancelled`、`failed` 视为失败。
等待超时仍未到终态、或记录缺失时返回失败，并保留具体原因；等待超时不代表交易所已撤销指令。
普通订单列表不承载这类指令，结果在 `memory.option_action` 中给出指令引用、张数和最终状态。
