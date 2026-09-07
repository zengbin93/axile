import { channelAccountFieldVisible } from '@/features/setup/channelAccountFields'
import type { Account, ChannelAccountField } from '@/types/api'

/** 初始化连接编辑草稿；敏感值绝不带入输入框。 */
export function initialConnectionDraft(
  account: Pick<Account, 'account_configured' | 'connection_values'>,
  fields: ChannelAccountField[],
): Record<string, unknown> {
  return Object.fromEntries(fields.map((field) => [
    field.name,
    field.kind === 'secret' ? '' : (account.connection_values?.[field.name] ?? field.default ?? ''),
  ]))
}

/** 将连接草稿转换为更新载荷；密钥留空时由服务端保留现有值。 */
export function mergedConnectionConfig(
  _account: Pick<Account, 'account_configured'>,
  fields: ChannelAccountField[],
  draft: Record<string, unknown>,
) {
  const next: Record<string, unknown> = {}
  for (const field of fields) {
    if (!channelAccountFieldVisible(field, draft)) continue
    const drafted = draft[field.name]
    const value = drafted
    if (value !== undefined && value !== null && value !== '') next[field.name] = value
  }
  return next
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonical(item)]),
    )
  }
  return value
}

/** 比较连接配置的语义内容，忽略 JSON 对象键顺序。 */
export function sameConnectionConfig(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right))
}
