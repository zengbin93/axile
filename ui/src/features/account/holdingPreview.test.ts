import { describe, expect, it } from 'bun:test'
import { currentHoldingPreview, rebalanceTurnover } from './holdingPreview'
import type { RebalancePlan, RebalanceRow } from '@/lib/derive'

function row(symbol: string, amount: number, action: RebalanceRow['action']): RebalanceRow {
  return {
    symbol,
    cur: 0,
    tgt: amount,
    delta: -amount,
    amount,
    side: action === 'aligned' ? 'none' : 'buy',
    action,
  }
}

const plan: RebalancePlan = {
  rows: [row('small', 2, 'open'), row('aligned', 20, 'aligned'), row('large', 12, 'open'), row('mid', 5, 'flip')],
  off: 3,
  buys: 3,
  sells: 0,
  flips: 1,
  netExposure: 0,
  grossExposure: 0,
  targetNet: 19,
}

describe('currentHoldingPreview', () => {
  it('按品种与方向聚合，并按市值绝对值排列', () => {
    const rows = currentHoldingPreview([
      { symbol: 'rb2610', direction: '多头', market_value: 20_000 },
      { symbol: 'ag2610', direction: '空头', market_value: 60_000 },
      { symbol: 'rb2610', direction: 'long', market_value: 10_000 },
    ], 100_000)

    expect(rows).toEqual([
      { key: 'ag2610:short', symbol: 'ag2610', direction: 'short', weight: -60, value: -60_000 },
      { key: 'rb2610:long', symbol: 'rb2610', direction: 'long', weight: 30, value: 30_000 },
    ])
  })

  it('权益未知时保留持仓市值但不编造权重', () => {
    expect(currentHoldingPreview([{ symbol: 'rb2610', market_value: 12_000 }], 0)[0]).toEqual({
      key: 'rb2610:long',
      symbol: 'rb2610',
      direction: 'long',
      weight: null,
      value: 12_000,
    })
  })
})

describe('rebalanceTurnover', () => {
  it('只汇总未到位品种的绝对权重差', () => {
    expect(rebalanceTurnover(plan)).toBe(19)
  })
})
