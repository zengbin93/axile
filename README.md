# Axile

Axile 是一个通过 Web UI 配置和运行的多渠道交易执行服务。

## 使用

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 和 [Bun](https://bun.sh/)。

```bash
uv sync

cd ui
bun install
bun run build
cd ..

uv run axile
```

启动后访问 <http://127.0.0.1:8000>。

使用 CTP、GM 或天勤渠道时，分别在同步依赖时添加 `--extra ctp`、`--extra gm` 或 `--extra tqsdk`。GM SDK 仅支持 Windows x86_64 和 Linux x86_64；macOS 会自动跳过该依赖，因此无法使用 GM 渠道。

天勤渠道支持实盘、快期模拟和本地模拟三种账户模式。组合中的国内衍生品代码沿用 CTP
`InstrumentID`（如 `rb2610`）；Axile 会在 TqSdk 执行器边界转换为 `SHFE.rb2610`。
本地模拟状态随日盘、夜盘前的常驻 Worker 重建而重置，需要持久模拟状态时使用快期模拟。
