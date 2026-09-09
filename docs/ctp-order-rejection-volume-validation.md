# 拒单关联与数量限制：离线验证

2026-09-09，仅修改 Axile；未连接柜台、提交 Git、发版或发送实盘订单。

## 行为

- 拒单以交易日、FrontID、SessionID、OrderRef 的完整稳定键关联。缺失会话字段使用当前发单会话，非法字段及交易日冲突只记录诊断；早到拒单由 tracker 缓冲回放。
- 数量拆分同时满足最小量和最大量，优先完整覆盖且订单数最少。例如 `12/3/10 → [9,3]`；不可完整覆盖时 `5/3/4 → [4]`，记录缺口 1，绝不向上凑量。
- 市价兜底在父订单确认终态后重新读取 MARKET 边界；每笔子单保留方向、开平和交易规则，通过正常登记入口回放早到事件，关闭子单追单。批次提交期间不提前结束等待，中途失败保留已提交子单，恢复异常继续抛出。
- 不支持数量边界的渠道保留小数数量语义。最终成功判断仍以实际持仓是否达到目标为准。

## 环境与复现

实际验证使用发行层已有 Python 3.13.8 环境及 OpenCTP SDK。SDK 硬编码依赖 `zh_CN.GB18030`；仅设置 LANG 无法解决导入失败。临时生成 locale，无需修改系统 locale 或安装替身 SDK：

```bash
# 从 Axile 子模块目录执行
mkdir -p /tmp/axon-locales
localedef -i zh_CN -f GB18030 /tmp/axon-locales/zh_CN.GB18030
LOCPATH=/tmp/axon-locales ../.venv/bin/python -m pytest tests/unit/executor -q
../.venv/bin/ruff check axile/executor tests/unit/executor
../.venv/bin/basedpyright
```

`test_reject_tracker_integration.py` 使用实际 OpenCTP 请求对象、SPI、CTPExecutor、ExecutionSession 和 OrderTracker，仅以 ScriptedBroker 替换 API 传输端。验证两种拒单回调、早到及重复拒单、同号不同会话订单隔离、显式会话身份、边界代理及原生发单前最小量校验。它是离线链路验证，不代表柜台联调。

## 结果与限制

- executor 测试 **839 项全部通过**（原有 785 项，新增 54 项）。
- Ruff 静态检查、改动文件格式检查、拆单/关联/tracker/TARGET-POS 复杂度检查通过。
- 项目配置范围内 BasedPyright：0 errors、0 warnings；额外检查本次修改的关联、数量、会话、tracker 和 TARGET-POS 文件也通过。
- 额外直接检查整个 `ctp_execute.py` 时，仍有 **13 项既有类型错误**及 4 项 SDK 源码解析警告。已与 HEAD 版本核对：涉及合约对象类型、可空恢复快照/API、SDK 请求和订阅签名、`UNAVAILABLE` 状态字面量及期权字段。该文件不在项目默认类型检查 include 中，本次没有扩展修改这些无关路径。

## 审查回归：有符号 SessionID

SessionID 使用 CTP 有符号 32 位整数范围，接受负数与零；仍拒绝布尔值、小数、畸形字符串和越界整数。FrontID 保留正数校验，完整稳定键保留 SessionID 符号。

修复前新增真实 SDK 离线用例复现 4 项失败、2 项通过。修复后正负会话相同 OrderRef 相互隔离，缺失会话字段的原生早到拒单可回放，显式负数会话及重复回报均正确收敛；839 项 executor 测试全部通过，相关 Ruff 和类型检查通过。
