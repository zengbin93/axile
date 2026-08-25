import { describe, expect, it } from 'bun:test'
import { rebalanceTurnover, topHoldingAdjustments } from './holdingPreview'
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

describe('topHoldingAdjustments', () => {
  it('排除到位项并按待调整幅度取前 N 项', () => {
    expect(topHoldingAdjustments(plan, 1_000_000, 2).map(({ row }) => row.symbol)).toEqual(['large', 'mid'])
  })

  it('按权益换算调整金额，权益未知时不编金额', () => {
    expect(topHoldingAdjustments(plan, 1_000_000, 1)[0]?.value).toBe(120_000)
    expect(topHoldingAdjustments(plan, 0, 1)[0]?.value).toBeNull()
  })
})

describe('rebalanceTurnover', () => {
  it('只汇总未到位品种的绝对权重差', () => {
    expect(rebalanceTurnover(plan)).toBe(19)
  })
})
