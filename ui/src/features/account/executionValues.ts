type Dict = Record<string, unknown>
export function dict(value: unknown): Dict {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Dict : {}
}
export function number(value: unknown): number | null {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}
function string(value: unknown): string { return typeof value === 'string' ? value : '' }
export function sideOf(value: unknown): 'buy' | 'sell' | 'none' {
  const side = string(value).toLowerCase()
  return side === 'buy' || side === 'sell' ? side : 'none'
}

export function shanghaiTime(value: string): number {
  const iso = value.replace(' ', 'T')
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}+08:00`)
}

