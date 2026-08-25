import { describe, expect, it } from 'bun:test'
import { currentHoldingPreview, formatHoldingQuantity, rebalanceTurnover } from './holdingPreview'
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
      { symbol: 'rb2610', direction: '多头', volume: 12, available_volume: 10, market_value: 20_000 },
      { symbol: 'ag2610', direction: '空头', volume: 8, available_volume: 8, market_value: 60_000 },
      { symbol: 'rb2610', direction: 'long', volume: 3, available_volume: 2, market_value: 10_000 },
    ], 100_000)

    expect(rows).toEqual([
      {
        key: 'ag2610:short',
        symbol: 'ag2610',
        direction: 'short',
        weight: -60,
        volume: 8,
        availableVolume: 8,
        value: -60_000,
      },
      {
        key: 'rb2610:long',
        symbol: 'rb2610',
        direction: 'long',
        weight: 30,
        volume: 15,
        availableVolume: 12,
        value: 30_000,
      },
    ])
  })

  it('同品种的多空持仓保持分行', () => {
    const rows = currentHoldingPreview([
      { symbol: 'rb2610', direction: '多头', volume: 2, available_volume: 1, market_value: 20_000 },
      { symbol: 'rb2610', direction: '空头', volume: 3, available_volume: 2, market_value: 10_000 },
    ], 100_000)

    expect(rows.map(({ key, volume, availableVolume }) => ({ key, volume, availableVolume }))).toEqual([
      { key: 'rb2610:long', volume: 2, availableVolume: 1 },
      { key: 'rb2610:short', volume: 3, availableVolume: 2 },
    ])
  })

  it('聚合数量存在缺失时保留未知状态', () => {
    const rows = currentHoldingPreview([
      { symbol: 'rb2610', volume: 2, available_volume: 1, market_value: 20_000 },
      { symbol: 'rb2610', available_volume: 2, market_value: 10_000 },
      { symbol: 'ag2610', volume: 3, market_value: 5_000 },
    ], 100_000)

    expect(rows.map(({ symbol, volume, availableVolume }) => ({ symbol, volume, availableVolume }))).toEqual([
      { symbol: 'rb2610', volume: null, availableVolume: 3 },
      { symbol: 'ag2610', volume: 3, availableVolume: null },
    ])
  })

  it('权益未知时保留持仓市值但不编造权重', () => {
    expect(currentHoldingPreview([{ symbol: 'rb2610', volume: 2, available_volume: 1, market_value: 12_000 }], 0)[0]).toEqual({
      key: 'rb2610:long',
      symbol: 'rb2610',
      direction: 'long',
      weight: null,
      volume: 2,
      availableVolume: 1,
      value: 12_000,
    })
  })
})

describe('formatHoldingQuantity', () => {
  it('格式化整数、小数和极小非零数量', () => {
    expect(formatHoldingQuantity(12_000)).toBe('12,000')
    expect(formatHoldingQuantity(1.23)).toBe('1.23')
    expect(formatHoldingQuantity(0.1234567)).toBe('0.123457')
    expect(formatHoldingQuantity(0.0000001)).toBe('<0.000001')
    expect(formatHoldingQuantity(0)).toBe('0')
  })

  it('无效数量显示为未知', () => {
    expect(formatHoldingQuantity(null)).toBe('—')
    expect(formatHoldingQuantity(undefined)).toBe('—')
    expect(formatHoldingQuantity(Number.NaN)).toBe('—')
    expect(formatHoldingQuantity(Number.POSITIVE_INFINITY)).toBe('—')
    expect(formatHoldingQuantity(-1)).toBe('—')
  })
})

describe('rebalanceTurnover', () => {
  it('只汇总未到位品种的绝对权重差', () => {
    expect(rebalanceTurnover(plan)).toBe(19)
  })
})
