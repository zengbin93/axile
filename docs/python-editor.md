# Python 组合函数编辑器

组合编辑页使用 CodeMirror 6 与 `@codemirror/lsp-client`，后端运行 `ty server`。
安装 Axile 时同时安装 ty 和 Ruff，不需要另行启动语言服务。

## 编辑与语言能力

- 行号、折叠 gutter、4 空格自动缩进、缩进参考线、括号匹配与自动闭合。
- 查找和替换（支持大小写、全词及正则）、撤销/重做、多光标、注释与移动行。
- ty 补全（含自动导入）、类型诊断、Hover 文档、函数参数提示。
- 定义跳转、引用列表、草稿内重命名、快速修复。
- 语义着色、内联类型/参数提示和 ty 提供的折叠范围；断线时保留本地语法折叠。
- Ruff 文档格式化作为一次可撤销操作；请求期间继续输入时不会被迟到结果覆盖。

`Ctrl/Cmd+F` 查找，Windows/Linux `Ctrl+H`、macOS `Cmd+Option+F` 替换；
`Shift+Alt+F` 格式化，`Ctrl/Cmd+/` 注释，`Alt+↑/↓` 移动行，
`Ctrl/Cmd+D` 多选相同词，`Ctrl/Cmd+G` 跳转行。
`F12` 定义、`Shift+F12` 引用、`F2` 重命名、`Ctrl/Cmd+.` 快速修复。
`Tab/Shift+Tab` 缩进；按 `Escape` 后再按 `Tab` 可离开编辑器。
组合工作台保留 `Ctrl/Cmd+S` 保存、`Ctrl/Cmd+Enter` 试跑。

新建组合模板显式导入 `axile.server.context.Context` 并标注参数类型，
因此 `context.` 能补全账户、持仓和行情接口。旧代码仍然可用；给参数补上
类型注解可以获得更完整的提示。语言服务使用后端同一个 Python 环境解析依赖。

代码问题与试跑结果独立展示。静态检查不执行用户代码，也不代表试跑通过。
编辑代码后旧试跑结果保留并标注过期，其代码行标记失效。静态诊断不抢焦点或滚动页面。

## 会话与边界

`/api/v1/editor/lsp` 将 WebSocket JSON 桥接到 ty stdio；每个连接拥有独立的
临时目录、文档 URI 与进程。离开页面即回收；空闲 10 分钟回收，最多同时 8 个会话。
前端断线后自动退避重连并同步当前未保存草稿，编辑内容、光标和撤销历史留在本地。
服务仅用于已有的本机回环部署，并检查 WebSocket 同源 Origin。

`POST /api/v1/editor/format` 接受 `{ "code": "..." }` 并返回同形结果，
使用 Ruff 独立默认配置；不会读取或修改用户项目格式化配置。

定义和引用可打开当前 Python 环境及 Axile 包中的 `.py` / `.pyi` 只读预览。
工作区第一版只编辑一个草稿；需要修改其他文件的重命名或 quick fix 整体拒绝。
不提供任意路径文件读写、工作区命令执行或文件创建能力。

## 验证

```bash
uv sync --locked --group dev
uv run pytest tests/unit/server/test_editor_routes.py -v
cd ui
bun install --frozen-lockfile
bunx playwright install chromium
bun run test:e2e
```

浏览器测试启动独立的 1438/1439 端口服务，仅挂载编辑器路由，不连接数据库、
真实账户或交易调度器。覆盖真实 ty 交互、格式化撤销、搜索替换、重连、
运行错误与静态错误共存，以及基本编辑快捷键。
