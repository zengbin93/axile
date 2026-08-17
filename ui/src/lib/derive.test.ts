import { expect, test } from 'bun:test'
import { integrityOf, gateOf, stateVerdict } from './derive'
import type { AccountDashboardItem } from '../types/api'

/** 造一个仪表盘项；只填两轴关心的字段，其余给中性占位。 */
function item(over: Partial<AccountDashboardItem>): AccountDashboardItem {
  return {
    account_id: 1,
    name: 'testnet',
    market: 'crypto',
    trade_channel: 'paper',
    is_started: true,
    portfolio_id: null,
    is_scheduled: false,
    next_run_time: null,
    total_asset: 0,
    currency: 'USDT',
    holdings_count: 0,
    position_weights: [],
    equity_series: [],
    last_is_success: null,
    last_exec_at: null,
    ...over,
  }
}

// ── 在位性（风险轴）：只由执行结果派生 ──

test('上次成功 → 在位', () => {
  expect(integrityOf(item({ last_is_success: 1, last_exec_at: '2026-07-21T12:00:00' })).integrity).toBe('aligned')
})

test('上次失败 → 偏离', () => {
  expect(integrityOf(item({ last_is_success: 0, last_exec_at: '2026-07-21T12:53:25' })).integrity).toBe('off')
})

test('无记录 → 未知（不无证推定良好）', () => {
  expect(integrityOf(item({ last_is_success: null, last_exec_at: null })).integrity).toBe('unknown')
})

test('有记录但结果缺失 → 未知（比旧 statusFromItem 的「else→到位」更诚实）', () => {
  expect(integrityOf(item({ last_is_success: null, last_exec_at: '2026-07-21T12:00:00' })).integrity).toBe('unknown')
})

// ── 档位（模式轴）：只由 is_started 派生 ──

test('is_started=true → 自动', () => {
  expect(gateOf(item({ is_started: true })).gate).toBe('auto')
})

test('is_started=false → 暂停', () => {
  expect(gateOf(item({ is_started: false })).gate).toBe('paused')
})

// ── 正交性：暂停不再吃掉失败（截图那格） ──

test('暂停 + 上次失败：档位=暂停 且 在位性=偏离（两轴各说各的，失败不被遮）', () => {
  const it = item({ is_started: false, last_is_success: 0, last_exec_at: '2026-07-21T12:53:25' })
  expect(gateOf(it).gate).toBe('paused')
  // 旧 statusFromItem 在这里会因 is_started=false 短路成「暂停」，把偏离吞掉。
  expect(integrityOf(it).integrity).toBe('off')
})

// ── 四象限判词：模式给风险改台词 ──

test('自动 + 偏离 + 低敞口 → 会自动重试（不加重）', () => {
  const v = stateVerdict(item({ is_started: true, last_is_success: 0, last_exec_at: '2026-07-21T12:53:25', total_asset: 1000, position_weights: [200] }))
  expect(v.text).toBe('上次未到位 · 将自动重试')
  expect(v.loud).toBe(false)
})

test('自动 + 偏离 + 高杠杆 → 敞口偏高（加重）', () => {
  const v = stateVerdict(item({ is_started: true, last_is_success: 0, last_exec_at: 't', total_asset: 1000, position_weights: [900, 700] }))
  expect(v.text).toContain('敞口偏高')
  expect(v.loud).toBe(true)
})

test('暂停 + 偏离 → 需手动（加重，最坏格）', () => {
  const v = stateVerdict(item({ is_started: false, last_is_success: 0, last_exec_at: '2026-07-21T12:53:25' }))
  expect(v.text).toContain('需手动')
  expect(v.loud).toBe(true)
})

test('在位 / 未知 与档位无关、皆不加重', () => {
  expect(stateVerdict(item({ is_started: false, last_is_success: 1, last_exec_at: 't' })).loud).toBe(false)
  expect(stateVerdict(item({ is_started: false, last_is_success: null })).loud).toBe(false)
})
