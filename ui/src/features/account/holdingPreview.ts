import type { RebalancePlan } from '@/lib/derive'
import type { Position } from '@/types/api'

export interface CurrentHoldingPreview {
  key: string
  symbol: string
  direction: 'long' | 'short'
  weight: number | null
  value: number | null
}

function isShort(direction: unknown): boolean {
  return typeof direction === 'string' && (direction.includes('空') || direction.toLowerCase().includes('short'))
}

/** 按品种与方向聚合当前持仓，并按持仓市值绝对值降序排列。 */
export function currentHoldingPreview(
  positions: Position[],
  equity: number,
): CurrentHoldingPreview[] {
  const holdings = new Map<string, { symbol: string; direction: 'long' | 'short'; value: number | null }>()

  for (const position of positions) {
    const symbol = typeof position.symbol === 'string' ? position.symbol.trim() : ''
    if (!symbol) continue
    const direction = isShort(position.direction) ? 'short' : 'long'
    const key = `${symbol}:${direction}`
    const rawValue = Number(position.market_value)
    const value = Number.isFinite(rawValue) ? Math.abs(rawValue) : null
    const previous = holdings.get(key)
    holdings.set(key, {
      symbol,
      direction,
      value: value == null ? previous?.value ?? null : (previous?.value ?? 0) + value,
    })
  }

  return [...holdings.entries()]
    .map(([key, holding]) => {
      const signedValue = holding.value == null ? null : holding.direction === 'short' ? -holding.value : holding.value
      return {
        key,
        symbol: holding.symbol,
        direction: holding.direction,
        weight: signedValue != null && equity > 0 ? (signedValue / equity) * 100 : null,
        value: signedValue,
      }
    })
    .toSorted((left, right) => Math.abs(right.value ?? 0) - Math.abs(left.value ?? 0))
}

/** 预计总换手为所有待调整品种绝对权重差之和。 */
export function rebalanceTurnover(plan: RebalancePlan): number {
  return plan.rows
    .filter((row) => row.action !== 'aligned')
    .reduce((sum, row) => sum + row.amount, 0)
}
