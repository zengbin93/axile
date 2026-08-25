# Axile

Axile 是一个通过 Web UI 配置和运行的多渠道交易执行服务。

## 使用

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 [Bun](https://bun.sh/)。

```bash
uv sync

cd ui
bun install
bun run build
cd ..

uv run axile
```

启动后访问 <http://127.0.0.1:8000>。

使用 CTP、GM、天勤、Shinny 或 Tushare 交易日历兜底时，分别在同步依赖时添加 `--extra ctp`、`--extra gm`、`--extra tqsdk`、`--extra shinny` 或 `--extra tushare`。GM SDK 仅支持 Windows x86_64 和 Linux x86_64；macOS 会自动跳过该依赖，因此无法使用 GM 渠道。

Shinny 兜底会固定按自然日 `00:00` 物化 `china` 日历，仅适用于中国期货和通用节假日；内置节假日数据截至 `2026-12-31`，之后不会生成记录。它不承诺 A 股交易所级准确性，A 股请使用 Tushare、CSV 或自定义函数。

Tushare 兜底通过 `trade_cal(exchange="SSE")` 维护 A 股和国内期货共用的中国交易日历，需在初始化向导或受管 `config.toml` 设置 `tushare_token`。`trade_cal` 需要 ≥2000 积分；Token 仅在刷新阶段运行时读取，不会写入日历函数、日志或接口响应。

天勤渠道支持实盘、快期模拟和本地模拟三种账户模式。组合中的国内衍生品代码沿用 CTP
`InstrumentID`（如 `rb2610`）；Axile 会在 TqSdk 执行器边界转换为 `SHFE.rb2610`。
本地模拟状态随日盘、夜盘前的常驻 Worker 重建而重置，需要持久模拟状态时使用快期模拟。
