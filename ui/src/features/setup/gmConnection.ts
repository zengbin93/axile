/** GM 连接目标的前端选择模式。 */
export type GMConnectionMode = 'terminal' | 'service'

/** 返回 GM 连接配置中第一个缺失字段对应的提示。 */
export function gmConnectionError(config: Record<string, string>, mode: GMConnectionMode): string | null {
  if (!config.account_id?.trim()) return '请填写账号 ID'
  if (!config.token?.trim()) return '请填写 Token'
  if (mode === 'terminal' && !config.terminal_path?.trim()) return '请填写掘金终端目录'
  if (mode === 'service' && !config.serv_addr?.trim()) return '请填写终端 RPC 地址'
  return null
}

/** 生成只包含当前连接目标的 GM 配置，避免提交互斥字段或空字符串。 */
export function normalizeGMConnection(config: Record<string, string>, mode: GMConnectionMode): Record<string, string> {
  const normalized: Record<string, string> = {
    account_id: config.account_id?.trim() ?? '',
    token: config.token?.trim() ?? '',
  }
  const targetKey = mode === 'terminal' ? 'terminal_path' : 'serv_addr'
  const targetValue = config[targetKey]?.trim()
  if (targetValue) normalized[targetKey] = targetValue
  return normalized
}

/** 切换 GM 连接方式，并立即移除不再生效的互斥字段。 */
export function switchGMConnectionMode(config: Record<string, string>, mode: GMConnectionMode): Record<string, string> {
  const nextConfig = { ...config }
  delete nextConfig[mode === 'terminal' ? 'serv_addr' : 'terminal_path']
  return nextConfig
}
