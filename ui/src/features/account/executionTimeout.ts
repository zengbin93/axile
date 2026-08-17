import type { TradeChannel } from '@/types/api'
import { getChannelDescriptor } from '@/stores/channels'

/** 返回渠道对应的账户执行超时默认值（秒）。 */
export function defaultExecutionTimeoutForChannel(channel: TradeChannel): string {
  return String(getChannelDescriptor(channel)?.defaults.execution_timeout ?? 300)
}

/** 校验账户执行超时，与服务端 1..540 秒的整数边界保持一致。 */
export function executionTimeoutError(value: string, options: { allowEmpty?: boolean } = {}): string | null {
  if (value.trim() === '') return options.allowEmpty ? null : '请输入整数秒'
  const timeout = Number(value)
  if (!Number.isInteger(timeout)) return '需为整数秒'
  if (timeout < 1) return '需 ≥ 1 秒（该兜底不可关闭）'
  if (timeout > 540) return '需 ≤ 540 秒'
  return null
}

/** 将合法执行超时按 30 秒前后调整，并夹在服务端边界内。 */
export function stepExecutionTimeout(value: string, direction: -1 | 1): string {
  const timeout = Number(value)
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 540) return value
  return String(Math.min(540, Math.max(1, timeout + direction * 30)))
}
