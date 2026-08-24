import { describe, it, expect } from 'bun:test'

import { buildSymbolActionStream } from './actionStream'
import type { ExecutionEvent } from '@/types/api'

/** 造一条最小可用的执行事件。 */
function ev(patch: Partial<ExecutionEvent>): ExecutionEvent {
  return {
    id: null,
    execution_id: 'e',
    account_id: 1,
    channel: 'PAPER',
    algorithm: 'single-maker',
    event_type: 'order_submitted',
    status: 'INFO',
    reason_code: '',
    reason_family: 'EXECUTION_STRATEGY',
    symbol: 'rb2610',
    order_id: null,
    client_order_id: null,
    ts_local_created: '2026-07-14T23:17:08',
    seq: 0,
    details: {},
    ...patch,
  } as ExecutionEvent
}

describe('buildSymbolActionStream', () => {
  it('决策置顶，即便其时间戳晚于成交（补发乱序已修）', () => {
    const lines = buildSymbolActionStream(
      [
        ev({
          event_type: 'order_terminal',
          seq: 5,
          status: 'SUCCESS',
          order_id: 'o1',
          ts_local_created: '2026-07-14T23:17:16',
          details: { order: { direction: 'OrderDirection.BUY', terminal_status: 'FILLED', volume: 0.0756, filled_volume: 0.0756, avg_price: 62000 } },
        }),
        // 决策补发在末尾，时间戳最晚：
        ev({
          event_type: 'symbol_decision_made',
          seq: 9,
          ts_local_created: '2026-07-14T23:17:20',
          details: { decision: { algorithm: 'single-maker', target_volume: 0.0756, orders_count: 1, status: 'SUCCEEDED' } },
        }),
        ev({
          event_type: 'order_submitted',
          seq: 2,
          order_id: 'o1',
          ts_local_created: '2026-07-14T23:17:08',
          details: { order: { direction: 'OrderDirection.BUY', volume: 0.0756, price: 61990 } },
        }),
      ],
      'rb2610',
    )

    expect(lines.map((l) => l.text)).toEqual([
      '决策 · 目标仓 0.0756 · single-maker · 1 单',
      '挂单 买 0.0756 @61,990',
      '成交 买 0.0756/0.0756 @62,000',
    ])
    expect(lines.every((l) => l.symbol === null)).toBe(true)
    // 三态：决策/挂单为中性过程步，成交为 accent 蓝正向确认，均非断点
    expect(lines.map((l) => [l.good, l.broken])).toEqual([
      [false, false],
      [false, false],
      [true, false],
    ])
  })

  it('追价成流，且抑制被追价撤掉的旧单终态', () => {
    const lines = buildSymbolActionStream(
      [
        ev({ event_type: 'order_submitted', seq: 1, order_id: 'o1', ts_local_created: '2026-07-14T23:17:08', details: { order: { direction: 'OrderDirection.BUY', volume: 1, price: 100 } } }),
        ev({ event_type: 'order_submitted', seq: 2, order_id: 'o2', reason_code: 'COMMON.ORDER_CHASE', ts_local_created: '2026-07-14T23:17:13', details: { chase: { index: 1, max: 5, from_price: 100, to_price: 101, prev_order_id: 'o1' } } }),
        // o1 被追价撤掉的终态——应被抑制：
        ev({ event_type: 'order_terminal', seq: 3, status: 'SUCCESS', order_id: 'o1', ts_local_created: '2026-07-14T23:17:14', details: { order: { direction: 'OrderDirection.BUY', terminal_status: 'CANCELED', volume: 1, filled_volume: 0 } } }),
        ev({ event_type: 'order_terminal', seq: 4, status: 'SUCCESS', order_id: 'o2', ts_local_created: '2026-07-14T23:17:20', details: { order: { direction: 'OrderDirection.BUY', terminal_status: 'FILLED', volume: 1, filled_volume: 1, avg_price: 101 } } }),
      ],
      'rb2610',
    )

    expect(lines.map((l) => l.text)).toEqual([
      '挂单 买 1 @100',
      '追价 → @101（第 1/5 次）',
      '成交 买 1/1 @101',
    ])
  })

  it('只取目标品种；跳过记为断点', () => {
    const events = [
      ev({ event_type: 'symbol_skipped', symbol: 'ag2612', seq: 1, reason_code: 'COMMON.SYMBOL_SKIPPED' }),
      ev({ event_type: 'symbol_decision_made', symbol: 'rb2610', seq: 2, details: { decision: { target_volume: 0.5 } } }),
    ]
    const ag = buildSymbolActionStream(events, 'ag2612')
    expect(ag.map((l) => [l.text, l.broken])).toEqual([['跳过 · 无需下单', true]])
    expect(buildSymbolActionStream(events, 'rb2610').length).toBe(1)
  })

  it('已知和未知原因码都不暴露内部枚举', () => {
    const known = buildSymbolActionStream(
      [ev({ event_type: 'symbol_skipped', symbol: 'ag2612', reason_code: 'COMMON.SUB_MIN_NOTIONAL' })],
      'ag2612',
    )
    const unknown = buildSymbolActionStream(
      [ev({ event_type: 'symbol_skipped', symbol: 'ag2612', reason_code: 'PLUGIN.UNKNOWN_REASON' })],
      'ag2612',
    )
    expect(known[0]?.text).toBe('跳过 · 未达到最小下单金额')
    expect(unknown[0]?.text).toBe('跳过 · 未执行')
  })

  it('无该品种事件 → 空流', () => {
    expect(buildSymbolActionStream([], 'rb2610')).toEqual([])
  })

  it('按渠道描述追加数量与价格单位', () => {
    const lines = buildSymbolActionStream(
      [
        ev({
          event_type: 'order_submitted',
          details: { order: { direction: 'OrderDirection.BUY', volume: 0.001234, price: 62000 } },
        }),
      ],
      'rb2610',
      { quantityLabel: '基础资产', quantityMaxDecimals: 3, priceLabel: 'CNY' },
    )

    expect(lines[0]?.text).toBe('挂单 买 0.001 基础资产 @62,000 元')
  })
})
