import { channelAccountFieldVisible } from '@/features/setup/channelAccountFields'
import type { Account, ChannelAccountField } from '@/types/api'

/** 初始化连接编辑草稿；敏感值绝不带入输入框。 */
export function initialConnectionDraft(
  account: Pick<Account, 'account_config'>,
  fields: ChannelAccountField[],
): Record<string, unknown> {
  return Object.fromEntries(fields.map((field) => [
    field.name,
    field.kind === 'secret' ? '' : (account.account_config[field.name] ?? field.default ?? ''),
  ]))
}

/** 将草稿合并回完整渠道配置，留空的敏感字段保留旧值。 */
export function mergedConnectionConfig(
  account: Pick<Account, 'account_config'>,
  fields: ChannelAccountField[],
  draft: Record<string, unknown>,
) {
  const next = { ...account.account_config }
  for (const field of fields) delete next[field.name]
  for (const field of fields) {
    if (!channelAccountFieldVisible(field, draft)) continue
    const drafted = draft[field.name]
    const value = field.kind === 'secret' && String(drafted ?? '').trim() === ''
      ? account.account_config[field.name]
      : drafted
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
