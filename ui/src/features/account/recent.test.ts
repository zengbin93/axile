import { expect, test } from 'bun:test'
import { buildRecentActivity } from './recent'
import type { AccountActivity, ExecutionActivity, ScheduleSkipActivity } from '../../lib/api/accounts'
import type { ExecuteRecord } from '../../types/api'

/** 造一条执行记录。kind: 'fill' | 'noop' | 'fail' | 'blocked'。 */
function rec(id: number, kind: 'fill' | 'noop' | 'fail' | 'blocked'): ExecuteRecord {
  const base = {
    id,
    execution_id: `e${id}`,
    created_at: `2026-07-02T10:${String(id % 60).padStart(2, '0')}:00`,
    raw_result: { account_assets: { total_asset: 1000 } },
  }
  if (kind === 'fail') return { ...base, is_success: 0, raw_input: {} }
  if (kind === 'blocked') {
    return {
      ...base,
      is_success: 0,
      raw_input: {},
      raw_result: { status: 'BLOCKED', error: '5 个品种因交易时段不可执行', account_assets: { total_asset: 1000 } },
    }
  }
  if (kind === 'noop') return { ...base, is_success: 1, raw_input: { curr_target: { rb2610: 0.5 }, last_target: { rb2610: 0.5 } } }
  return { ...base, is_success: 1, raw_input: { curr_target: { rb2610: 0.6 }, last_target: { rb2610: 0.5 } } }
}

function execution(record: ExecuteRecord): ExecutionActivity {
  return { kind: 'execution', occurred_at: record.created_at, record }
}

function executions(records: ExecuteRecord[]): AccountActivity[] {
  return records.map(execution)
}

function skip(id: number, occurredAt: string): ScheduleSkipActivity {
  return {
    kind: 'schedule_skip',
    occurred_at: occurredAt,
    id,
    channel: 'ctp',
    reason_code: 'CALENDAR.CLOSED',
    calendar_day: occurredAt.slice(0, 10),
    calendar_id: 'china',
    calendar_label: '中国交易日历',
  }
}

test('连续空跑折叠成一行并计数', () => {
  const { rows } = buildRecentActivity(executions([rec(3, 'noop'), rec(2, 'noop'), rec(1, 'noop')]))
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ type: 'noop', count: 3 })
})

test('连续失败折叠成一行并计数', () => {
  const { rows } = buildRecentActivity(executions([rec(3, 'fail'), rec(2, 'fail')]))
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ type: 'fail', count: 2, executionId: 'e3' })
})

test('失败折叠行保留最近一次可行动原因', () => {
  const latest = rec(3, 'fail')
  latest.raw_result = { error: 'CTP 交易前置断线: 4097' }
  const { rows } = buildRecentActivity(executions([latest]))
  expect(rows[0]).toMatchObject({ type: 'fail', reason: 'CTP 交易前置断线: 4097' })
})

test('成交逐条保留，含变动描述', () => {
  const { rows } = buildRecentActivity(executions([rec(1, 'fill')]))
  expect(rows[0]).toMatchObject({ type: 'fill', desc: '调仓执行 · 1 处变动' })
})

test('交错时按时间保序、分段折叠', () => {
  const { rows } = buildRecentActivity(executions([rec(4, 'fail'), rec(3, 'fail'), rec(2, 'fill'), rec(1, 'noop')]))
  expect(rows.map((r) => r.type)).toEqual(['fail', 'fill', 'noop'])
  expect(rows[0]).toMatchObject({ type: 'fail', count: 2 })
})

test('末尾失败组在窗口拉满时标记饱和(N+)', () => {
  const recs = Array.from({ length: 5 }, (_, k) => rec(5 - k, 'fail'))
  const { rows } = buildRecentActivity(executions(recs), { fetchLimit: 5 })
  expect(rows[0]).toMatchObject({ type: 'fail', count: 5, saturated: true })
})

test('未拉满窗口不标记饱和', () => {
  const recs = Array.from({ length: 3 }, (_, k) => rec(3 - k, 'fail'))
  const { rows } = buildRecentActivity(executions(recs), { fetchLimit: 50 })
  expect(rows[0]).toMatchObject({ saturated: false })
})

test('限量到 cap 并标记 truncated', () => {
  const recs = Array.from({ length: 10 }, (_, k) => rec(10 - k, 'fill'))
  const { rows, truncated } = buildRecentActivity(executions(recs), { cap: 6 })
  expect(rows).toHaveLength(6)
  expect(truncated).toBe(true)
})

test('连续休市跳过折叠，且不会生成可点击执行记录', () => {
  const { rows } = buildRecentActivity([
    skip(2, '2026-07-02T10:12:00+08:00'),
    skip(1, '2026-07-02T10:11:00+08:00'),
    execution(rec(1, 'fill')),
  ])
  expect(rows[0]).toMatchObject({ type: 'skip', count: 2 })
  expect('executionId' in rows[0]).toBe(false)
})

test('执行记录会切断休市跳过的连续分组', () => {
  const record = rec(9, 'fill')
  record.created_at = '2026-07-02T10:11:30+08:00'
  const { rows } = buildRecentActivity([
    skip(2, '2026-07-02T10:12:00+08:00'),
    execution(record),
    skip(1, '2026-07-02T10:11:00+08:00'),
  ])
  expect(rows.map((row) => row.type)).toEqual(['skip', 'fill', 'skip'])
})

test('BLOCKED 不与失败折叠，并保留原因', () => {
  const { rows } = buildRecentActivity(executions([rec(3, 'blocked'), rec(2, 'fail'), rec(1, 'blocked')]))
  expect(rows.map((row) => row.type)).toEqual(['blocked', 'fail', 'blocked'])
  expect(rows[0]).toMatchObject({ type: 'blocked', count: 1, reason: '5 个品种因交易时段不可执行' })
})

test('连续 BLOCKED 折叠成一行', () => {
  const { rows } = buildRecentActivity(executions([rec(3, 'blocked'), rec(2, 'blocked')]))
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ type: 'blocked', count: 2 })
})

test('BUSY 排程跳过用人话原因', () => {
  const busy = skip(9, '2026-08-26T10:00:00+08:00')
  busy.reason_code = 'BUSY'
  const { rows } = buildRecentActivity([busy])
  expect(rows[0]).toMatchObject({ type: 'skip', reason: '已有执行在途，本次排程跳过' })
})

test('进程中断失败记录用人话原因', () => {
  const interrupted = rec(4, 'fail')
  interrupted.raw_result = { error: '上次执行中断，未自动续跑', interrupt_reason: 'process_interrupted' }
  const { rows } = buildRecentActivity(executions([interrupted]))
  expect(rows[0]).toMatchObject({ type: 'fail', reason: '上次执行中断，未自动续跑' })
})
