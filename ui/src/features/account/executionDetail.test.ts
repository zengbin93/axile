import { describe, it, expect } from 'bun:test'

import { buildExecutionDetail, formatOrderTradeCounts } from './executionDetail'
import type { ExecutionArtifact, ExecutionEvent, ExecutionStatus } from '@/types/api'

/** 造一条最小可用的执行事件。 */
function ev(patch: Partial<ExecutionEvent>): ExecutionEvent {
  return {
    event_type: 'execution_started',
    status: 'INFO',
    reason_code: '',
    reason_family: 'SYSTEM',
    symbol: null,
    ts_local_created: '2026-07-14T10:18:08',
    seq: 0,
    details: {},
    ...patch,
  } as ExecutionEvent
}

/** 造一个附件。 */
function art(type: string, content: Record<string, unknown>): ExecutionArtifact {
  return { id: null, execution_id: 'e', artifact_type: type, content, created_at: '' }
}

/** 一组「两只减仓、全部到位」的真实形态 fixture（对应 4c05）。 */
function baseFixture(): { events: ExecutionEvent[]; artifacts: ExecutionArtifact[] } {
  const events: ExecutionEvent[] = [
    ev({ event_type: 'execution_started', seq: 1, details: { debug: { trigger_source: 'manual', execution_kind: 'rebalance' } } }),
    ev({ event_type: 'input_snapshotted', seq: 2, details: { debug: { strategy_count: 0, symbol_count: 2 } } }),
    ev({ event_type: 'target_computed', seq: 3, details: { decision: { curr_target: { rb2610: 0.9, ag2612: 0.9 } } } }),
    ev({
      event_type: 'order_terminal',
      seq: 4,
      status: 'SUCCESS',
      symbol: 'ag2612',
      ts_local_created: '2026-07-14T10:18:27',
      details: {
        order: { direction: 'OrderDirection.SELL', terminal_status: '已成交', filled_ratio: 1.0 },
        exchange: { client_order_id: 'lIww' },
      },
    }),
    ev({
      event_type: 'symbol_decision_made',
      seq: 6,
      status: 'SUCCESS',
      symbol: 'ag2612',
      details: { decision: { algorithm: 'SINGLE-MAKER', status: 'SUCCEEDED', target_volume: 2.599, orders_count: 1 } },
    }),
    ev({ event_type: 'execution_completed', seq: 8, status: 'SUCCESS', ts_local_created: '2026-07-14T10:18:50', details: { debug: { record_id: 9, success: true, execution_status: 'SUCCEEDED' } } }),
  ]
  const artifacts: ExecutionArtifact[] = [
    art('standard_input', {
      input: {
        curr_target: { ag2612: 0.9 },
        last_target: { ag2612: 1.5 },
        algorithm: { method: 'SINGLE-MAKER', params: { price_strategy: 'PASSIVE', chase_enabled: true, max_chase_count: 50, chase_interval: 5 } },
        forbidden_symbols: [],
        risk_symbols: [],
      },
    }),
    art('target_snapshot', { curr_target: { ag2612: 0.9 }, last_target: { ag2612: 1.5 } }),
    art('account_snapshot_before', {
      account_assets: { total_asset: 5147.62, market_value: 15620.7, positions: [{ symbol: 'ag2612', extra: { unrealized_pnl: 51.53 } }], source: 'real', update_time: '2026-07-14T10:18:08' },
      source: 'real',
    }),
    art('account_snapshot', {
      account_assets: { total_asset: 5176.1, market_value: 9265.26, positions: [{ symbol: 'ag2612', extra: { unrealized_pnl: 30.47 } }], source: 'real', update_time: '2026-07-14T10:18:49' },
    }),
    art('execution_summary', {
      summary: { symbols_total: 1, symbols_succeeded: 1, symbols_failed: 0, symbols_noop: 0 },
      success: true,
      execution_time: 41.2,
      reconciliation: {
        account: { equity_before: 5147.62, equity_after: 5176.1, source_before: 'real', source_after: 'real' },
        symbols: [
          { symbol: 'ag2612', status: 'SUCCEEDED', target: 2.599, filled: -1.794, filled_value: -3198.0, avg_price: 1782.73, before: 4.393, after: 2.599, moved: -1.794, drift: 0, attained_ratio: 1.0, reached: true },
        ],
      },
    }),
  ]
  return { events, artifacts }
}

describe('buildExecutionDetail · 头条', () => {
  it('status 失败在空事件和空附件时仍生成真实失败判词', () => {
    const task = {
      execution_id: 'e', account_id: 3, execution_kind: null, status: 'FAILED',
      created_at: '2026-08-25T11:32:05', started_at: null, finished_at: '2026-08-25T11:32:05',
      error: '调仓执行失败, 错误原因: CTP 交易前置断线: 4097', record_id: 36, is_success: 0,
      cancel_requested_at: null, cancel_reason: null, terminate_mode: null,
    } satisfies ExecutionStatus
    const model = buildExecutionDetail([], [], task)
    expect(model.failure?.category).toBe('CTP 连接')
    expect(model.task?.started_at).toBeNull()
    expect(model.header.totalCount).toBe(0)
  })

  it('汇总触发/耗时/到位/权益/敞口/来源', () => {
    const { events, artifacts } = baseFixture()
    const { header } = buildExecutionDetail(events, artifacts)
    expect(header.kind).toBe('rebalance')
    expect(header.trigger).toBe('manual')
    expect(header.durationSec).toBe(41.2)
    expect(header.reachedCount).toBe(1)
    expect(header.totalCount).toBe(1)
    expect(header.equityBefore).toBe(5147.62)
    expect(header.equityAfter).toBe(5176.1)
    expect(Math.round(header.exposureBefore ?? 0)).toBe(303)
    expect(Math.round(header.exposureAfter ?? 0)).toBe(179)
    expect(header.sourcePosition).toBe('real')
    expect(header.sourceEquity).toBe('real')
    expect(header.success).toBe(true)
  })

  it('项失败按逐只成交结果计，不重复计入生命周期 ERROR 回声', () => {
    const { events, artifacts } = baseFixture()
    // SR609 真失败（决策 ERROR、未到位/未知）
    events.push(
      ev({
        event_type: 'symbol_decision_made',
        seq: 7,
        status: 'ERROR',
        symbol: 'SR609',
        details: { decision: { algorithm: 'SINGLE-MAKER', status: 'FAILED', orders_count: 0 } },
      }),
    )
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    summary.content.success = false
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'SR609', status: 'FAILED', target: null, filled: 0, filled_value: 0, avg_price: null, before: 974.2, after: 974.2, moved: 0, drift: 0, attained_ratio: null, reached: null,
    })
    // 对账事件也标 ERROR —— 逐只失败的生命周期回声
    events.find((e) => e.event_type === 'execution_completed')!.status = 'ERROR'
    const header = buildExecutionDetail(events, artifacts).header
    // 2 条 ERROR 事件（SR609 决策 + 对账回声），但只有 1 个品种真失败
    expect(events.filter((e) => e.status === 'ERROR')).toHaveLength(2)
    expect(header.failedCount).toBe(1)
    expect(header.success).toBe(false)
  })
})

describe('formatOrderTradeCounts', () => {
  it('有成交明细时数笔', () => {
    expect(formatOrderTradeCounts(1, 1, true)).toBe('1 单 1 成交')
    expect(formatOrderTradeCounts(1, 1, true, ' · ')).toBe('1 单 · 1 成交')
  })

  it('订单已成但明细缺失时不喊 0 成交', () => {
    expect(formatOrderTradeCounts(1, 0, true)).toBe('1 单')
    expect(formatOrderTradeCounts(1, 0, true, ' · ')).toBe('1 单')
  })

  it('确实没成交时才写 0 成交', () => {
    expect(formatOrderTradeCounts(1, 0, false)).toBe('1 单 0 成交')
    expect(formatOrderTradeCounts(1, 0, false, ' · ')).toBe('1 单 · 0 成交')
  })
})

describe('buildExecutionDetail · 目标变化', () => {
  it('给出 last→curr 与算法参数摘要', () => {
    const { events, artifacts } = baseFixture()
    const tc = buildExecutionDetail(events, artifacts).targetChange
    expect(tc?.rows).toEqual([{ symbol: 'ag2612', curr: 0.9, last: 1.5 }])
    expect(tc?.algorithm).toBe('SINGLE-MAKER')
    expect(tc?.algoParams).toContain('PASSIVE')
    expect(tc?.algoParams).toContain('追价')
  })
})

describe('buildExecutionDetail · 逐只子链', () => {
  it('TCA 与订单树透传到 SymbolChain', () => {
    const { events, artifacts } = baseFixture()
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    const ag0 = (summary.content.reconciliation as { symbols: Record<string, unknown>[] }).symbols[0]!
    ag0.tca = { n_orders: 1, n_trades: 1, arrival_mid: 1782.66, slippage_bps: 0.36, liquidity: 'passive', fill_ratio: 1, fee: 0.64, fee_asset: 'CNY' }
    ag0.orders = [{ order_id: 'o1', side: 'sell', order_type: 'LIMIT', price: 1782.73, avg_price: 1782.73, volume: 1.794, filled_volume: 1.794, status: '已成交', client_order_id: 'lIww', trades: [{ price: 1782.73, volume: 1.794, value: 3198, time: '2026-07-14T10:18:26', fee: 0.64, fee_asset: 'CNY' }] }]
    const ag = buildExecutionDetail(events, artifacts).symbols[0]!
    expect(ag.tca?.liquidity).toBe('passive')
    expect(ag.tca?.slippage_bps).toBe(0.36)
    expect(ag.tca?.fee).toBe(0.64)
    expect(ag.orders).toHaveLength(1)
    expect(ag.orders[0]?.trades[0]?.fee).toBe(0.64)
  })

  it('减仓到位：方向/成交/均价/浮盈/耗时/无断点', () => {
    const { events, artifacts } = baseFixture()
    const ag = buildExecutionDetail(events, artifacts).symbols[0]!
    expect(ag.action).toBe('reduce')
    expect(ag.side).toBe('sell')
    expect(ag.filled).toBe(-1.794)
    expect(ag.filledValue).toBe(-3198.0)
    expect(ag.avgPrice).toBe(1782.73)
    expect(ag.reached).toBe(true)
    expect(ag.legSeconds).toBe(19)
    expect(ag.clientOrderId).toBe('lIww')
    expect(ag.pnlBefore).toBe(51.53)
    expect(ag.pnlAfter).toBe(30.47)
    expect(ag.broken).toBe(false)
  })

  it('撤销欠量：终态撤销 + reached=false → 断点变红并给原因', () => {
    const { events, artifacts } = baseFixture()
    // 改成 rb2610 撤销、欠量
    events.push(
      ev({
        event_type: 'order_terminal',
        seq: 5,
        status: 'WARNING',
        symbol: 'rb2610',
        details: { order: { direction: 'OrderDirection.BUY', terminal_status: '已撤销', filled_ratio: 0.74 }, exchange: { client_order_id: 'C4' } },
      }),
    )
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'rb2610', status: 'SUCCEEDED', target: 0.1243, filled: 0.0675, filled_value: 4197, avg_price: 62174, before: 0.0336, after: 0.1011, moved: 0.0675, drift: 0, attained_ratio: 0.81, reached: false,
    })
    const rb = buildExecutionDetail(events, artifacts).symbols.find((s) => s.symbol === 'rb2610')!
    expect(rb.terminalStatus).toBe('已撤销')
    expect(rb.reached).toBe(false)
    expect(rb.broken).toBe(true)
    expect(rb.reason).toContain('撤')
  })

  it('受阻且已到位：订单腿 BLOCKED 但仓位在目标 → 不判失败、不算断点、原因翻中文', () => {
    const { events, artifacts } = baseFixture()
    // 该动的量小到低于最小可交易粒度 → 决策 BLOCKED、未成交，但仓位天然在目标上。
    events.push(
      ev({
        event_type: 'symbol_decision_made',
        seq: 7,
        status: 'WARNING',
        symbol: 'm2609',
        details: { decision: { algorithm: 'SINGLE-MAKER', status: 'BLOCKED', orders_count: 0 } },
      }),
    )
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'm2609', status: 'BLOCKED', target: 2.372859, filled: 0, filled_value: 0, avg_price: null, before: 2.37, after: 2.37, moved: 0, drift: 0, attained_ratio: 0.9988, reached: true,
    })
    const m = buildExecutionDetail(events, artifacts).symbols.find((s) => s.symbol === 'm2609')!
    expect(m.reached).toBe(true)
    expect(m.action).not.toBe('failed')
    expect(m.broken).toBe(false)
    expect(m.reason).toBe('受阻')
  })

  it('受阻且未到位：订单腿 BLOCKED 且仓位掉出目标 → 判失败并断点，原因给「受阻」', () => {
    const { events, artifacts } = baseFixture()
    events.push(
      ev({
        event_type: 'symbol_decision_made',
        seq: 7,
        status: 'WARNING',
        symbol: 'm2609',
        details: { decision: { algorithm: 'SINGLE-MAKER', status: 'BLOCKED', orders_count: 0 } },
      }),
    )
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'm2609', status: 'BLOCKED', target: 3, filled: 0, filled_value: 0, avg_price: null, before: 1, after: 1, moved: 0, drift: 0, attained_ratio: 0.33, reached: false,
    })
    const m = buildExecutionDetail(events, artifacts).symbols.find((s) => s.symbol === 'm2609')!
    expect(m.reached).toBe(false)
    expect(m.action).toBe('failed')
    expect(m.broken).toBe(true)
    expect(m.reason).toBe('受阻')
  })

  it('真失败且结果未知：决策 FAILED、reached=null → 判失败并断点，原因行不回声英文/「失败」', () => {
    const { events, artifacts } = baseFixture()
    events.push(
      ev({
        event_type: 'symbol_decision_made',
        seq: 7,
        status: 'ERROR',
        symbol: 'SR609',
        details: { decision: { algorithm: 'SINGLE-MAKER', status: 'FAILED', orders_count: 0 } },
      }),
    )
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'SR609', status: 'FAILED', target: null, filled: 0, filled_value: 0, avg_price: null, before: 974.2, after: 974.2, moved: 0, drift: 0, attained_ratio: null, reached: null,
    })
    const sr = buildExecutionDetail(events, artifacts).symbols.find((s) => s.symbol === 'SR609')!
    expect(sr.reached).toBeNull()
    expect(sr.action).toBe('failed')
    expect(sr.broken).toBe(true)
    // FAILED 与头部「失败」同义反复 → 原因行留空，不吐 FAILED/失败
    expect(sr.reason).toBe('')
  })

  it('跳过：symbol_skipped → action=skipped + 原因 + 断点', () => {
    const { events, artifacts } = baseFixture()
    events.push(ev({ event_type: 'symbol_skipped', symbol: 'au2612', status: 'WARNING', reason_code: 'RISK.FORBIDDEN' }))
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'au2612', status: 'SKIPPED', target: 1, filled: 0, filled_value: 0, avg_price: null, before: 0, after: 0, moved: 0, drift: 0, attained_ratio: 0, reached: false,
    })
    const au = buildExecutionDetail(events, artifacts).symbols.find((s) => s.symbol === 'au2612')!
    expect(au.action).toBe('skipped')
    expect(au.broken).toBe(true)
    expect(au.reason).toBe('受账户交易限制')
  })
})

describe('buildExecutionDetail · 账户书签（证据）', () => {
  it('从前后快照与输入取现金/权益/市值/超时', () => {
    const { events, artifacts } = baseFixture()
    const before = artifacts.find((a) => a.artifact_type === 'account_snapshot_before')!
    ;(before.content.account_assets as Record<string, unknown>).available_cash = 4441.17
    const after = artifacts.find((a) => a.artifact_type === 'account_snapshot')!
    ;(after.content.account_assets as Record<string, unknown>).available_cash = 4755.75
    const std = artifacts.find((a) => a.artifact_type === 'standard_input')!
    ;(std.content.input as Record<string, unknown>).execution_timeout = 60
    const b = buildExecutionDetail(events, artifacts).bookends
    expect(b.cashBefore).toBe(4441.17)
    expect(b.cashAfter).toBe(4755.75)
    expect(b.equityBefore).toBe(5147.62)
    expect(b.mvAfter).toBe(9265.26)
    expect(b.timeoutSec).toBe(60)
  })
})

describe('buildExecutionDetail · 脊柱与降级', () => {
  it('脊柱含各节点、全 real 时不断且不吐裸枚举', () => {
    const { events, artifacts } = baseFixture()
    const spine = buildExecutionDetail(events, artifacts).spine
    const byKey = Object.fromEntries(spine.map((n) => [n.key, n]))
    // 逐只执行拆成阶段（这次两只都减仓 → 只有阶段1）
    expect(spine.map((n) => n.key)).toEqual(['started', 'input', 'before', 'target', 'phase1', 'after', 'completed'])
    expect(spine.every((n) => !n.broken)).toBe(true)
    // real 时账户节点保持安静（不显示 real）
    expect(byKey.before?.detail).toBe('')
    expect(byKey.after?.detail).toBe('')
    // 算目标不塌成单一值，只报变更方向
    expect(byKey.target?.detail).toBe('目标下调')
    // 阶段节点标并行、带到位
    expect(byKey.phase1?.label).toBe('阶段1 减仓')
    expect(byKey.phase1?.detail).toContain('并行 1 只')
    expect(byKey.phase1?.detail).toContain('1/1 到位')
    // 对账用人话、不吐 SUCCEEDED / #record_id
    expect(byKey.completed?.detail).toBe('成功')
  })

  it('有减有增 → 拆成 阶段1 减仓 + 阶段2 开仓（阶段1 全成才跑）', () => {
    const { events, artifacts } = baseFixture()
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { symbols: unknown[] }).symbols.push({
      symbol: 'au2612', status: 'SUCCEEDED', target: 10, filled: 10, filled_value: 1000, avg_price: 100, before: 0, after: 10, moved: 10, drift: 0, attained_ratio: 1, reached: true,
    })
    const spine = buildExecutionDetail(events, artifacts).spine
    const byKey = Object.fromEntries(spine.map((n) => [n.key, n]))
    expect(byKey.phase1?.label).toBe('阶段1 减仓') // ag2612 减仓
    expect(byKey.phase2?.label).toBe('阶段2 开仓') // au2612 建仓
    expect(byKey.phase2?.detail).toContain('阶段1 全成才跑')
    expect(byKey.target?.detail).toBe('目标下调') // 目标快照里只有 ag2612（下调）
  })

  it('执行前读账户降级：before 非 real → 只污染权益族，持仓族(到位度)仍为 real', () => {
    const { events, artifacts } = baseFixture()
    const before = artifacts.find((a) => a.artifact_type === 'account_snapshot_before')!
    before.content.source = 'assumed'
    ;(before.content.account_assets as { source: string }).source = 'assumed'
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { account: { source_before: string } }).account.source_before = 'assumed'
    const model = buildExecutionDetail(events, artifacts)
    // 权益族取两端较差 → assumed；到位度只依赖执行后快照 → 仍 real，不被 before 缺失污染。
    expect(model.header.sourceEquity).toBe('assumed')
    expect(model.header.sourcePosition).toBe('real')
    const beforeNode = model.spine.find((n) => n.key === 'before')
    expect(beforeNode?.broken).toBe(true)
    expect(beforeNode?.detail).toBe('假设值')
  })

  it('执行后快照降级：after 非 real → 持仓族与权益族均退化', () => {
    const { events, artifacts } = baseFixture()
    const summary = artifacts.find((a) => a.artifact_type === 'execution_summary')!
    ;(summary.content.reconciliation as { account: { source_after: string } }).account.source_after = 'error'
    const model = buildExecutionDetail(events, artifacts)
    expect(model.header.sourcePosition).toBe('error')
    expect(model.header.sourceEquity).toBe('error')
  })
})
