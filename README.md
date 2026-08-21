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

使用 CTP 或 GM 渠道时，分别在同步依赖时添加 `--extra ctp` 或 `--extra gm`。
