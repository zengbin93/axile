interface ContextField {
  name: string
  type: string
  desc: string
}

interface Example {
  key: string
  title: string
  desc: string
  code: string
}

export const CUSTOM_CALC_NOTES = [
  '权重为小数（0.5 = 半仓）；正数为多头，负数为空头。',
  '脚本在服务端的正常 Python 环境执行，可以导入已安装的包；依赖由部署环境统一提供。',
  '优先使用 `context` 的通用接口；只有渠道专有能力才直接使用 `context.executor`。',
  '`context.executor` 是完整、共享且常驻的真实渠道执行器；直接调用交易方法会立即产生渠道副作用。',
  '成功执行后 executor、回调和模块全局状态可能继续复用；请勿无意修改属性、遗留回调或启动永久后台线程。',
  '自定义资源应在 `finally` 中释放；脚本失败、超时或 worker 异常退出后，系统会在下次调用时重建 worker。',
  '不选择真实账户的样例试跑使用一次性进程和样例 executor，不连接真实渠道。',
  '发生异常时试跑会把错误标在出错的代码行上，据此定位问题后再重新试跑。',
]

/** 生成与页面内容一致、可直接粘贴到 Markdown 文档的纯文本。 */
export function buildCustomCalcMarkdown(
  contextFields: ContextField[],
  contractCode: string,
  examplesData: Example[],
  notesData: string[],
): string {
  const contextRows = contextFields.map((field) => `| \`${field.name}\` | \`${field.type}\` | ${field.desc} |`).join('\n')
  const examples = examplesData.map(
    (example) => `### ${example.title}\n\n${example.desc}\n\n\`\`\`python\n${example.code}\n\`\`\``,
  ).join('\n\n')
  const notes = notesData.map((note) => `- ${note}`).join('\n')

  return `# 开发自定义组合逻辑

自定义逻辑让你用一段 Python 决定组合「交易什么」。在本地写好并调试后，把 \`calculate_portfolio\` 函数粘贴到组合编辑器，点「试跑」跑一次确认无误（默认空跑，也可切到某真实账户）。

## 函数契约

脚本必须定义一个恰好接收一个参数的函数 \`calculate_portfolio(context)\`，返回一个「品种 → 目标权重」的字典（\`dict[str, float]\`）。返回空字典 \`{}\` 表示空仓。

\`\`\`python
${contractCode}
\`\`\`

标的格式由交易渠道决定；新建组合时请以当前市场自动生成的示例为准。

## 可用的 context 能力

\`context\` 基于统一模型提供账户、持仓、行情和订单查询。**空跑**使用固定样例账户和行情；切到某**真实账户**会准备该账户的真实渠道并执行实际查询，口径与真实调仓一致。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
${contextRows}

## 示例

${examples}

## 注意事项

${notes}
`
}
