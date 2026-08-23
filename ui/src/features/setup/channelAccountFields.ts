import type { ChannelAccountField } from '@/types/api'

/** 判断渠道账户字段在当前配置下是否可见。 */
export function channelAccountFieldVisible(
  field: ChannelAccountField,
  config: Record<string, unknown>,
): boolean {
  return !field.visible_when || config[field.visible_when.field] === field.visible_when.equals
}

/** 只保留当前模式可见的渠道账户配置。 */
export function visibleChannelAccountConfig(
  fields: ChannelAccountField[],
  config: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    fields
      .filter((field) => channelAccountFieldVisible(field, config))
      .map((field) => [field.name, config[field.name]])
      .filter((entry) => entry[1] !== undefined && entry[1] !== null),
  )
}

/** 更新一个字段，并立即移除因条件变化而隐藏的字段。 */
export function updateChannelAccountConfig(
  fields: ChannelAccountField[],
  config: Record<string, unknown>,
  name: string,
  value: unknown,
): Record<string, unknown> {
  const next = { ...config }
  if (value === undefined || value === null || value === '') delete next[name]
  else next[name] = value
  for (const field of fields) {
    if (!channelAccountFieldVisible(field, next)) delete next[field.name]
  }
  return next
}
