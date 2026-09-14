import { expect, test } from 'bun:test'
import { buildRecentActivity, recentRowText } from './recent'
import type { AccountActivity } from '@/lib/api/accounts'

function execution(id: number, outcome?: string, extra: Record<string, unknown> = {}): AccountActivity {
  return { kind: 'execution', occurred_at: `2026-09-14T14:${id}:00`, record: {
    id, execution_id: `e${id}`, created_at: `2026-09-14T14:${id}:00`, is_success: 0, raw_input: {},
    raw_result: { status: 'FAILED', outcome, ...extra },
  } }
}
const rows = (items: AccountActivity[], cap = 6, fetchLimit = 50) => buildRecentActivity(items, { cap, fetchLimit })

test('最新清仓成功保留在前，旧失败不覆盖最新结论', () => {
  const result = rows([execution(23, 'completed', { execution_kind: 'clear_positions' }), execution(10, 'error', { outcome_reason: '连接断开' })])
  expect(result.rows.map(recentRowText)).toEqual(['清仓完成', '执行失败 · 最近：连接断开'])
})
test('正常结束但全部未到位，不受 FAILED 与汇总 error 影响', () => {
  const result = rows([execution(23, 'not_reached', { error: '2 个品种执行未成功', symbol_results: { m2701: { outcome: 'not_reached' }, rb2701: { outcome: 'not_reached' } } })])
  expect(recentRowText(result.rows[0])).toBe('执行不到位 · m2701、rb2701')
})
test('连续未到位独立折叠，只展示最近一次品种', () => {
  const result = rows([execution(23, 'not_reached', { outcome_symbols: ['m2701'] }), execution(22, 'not_reached', { outcome_symbols: ['rb2701'] }), execution(21, 'error')])
  expect(result.rows).toHaveLength(2)
  expect(recentRowText(result.rows[0])).toBe('连续 2 次执行不到位 · m2701')
  expect(result.rows[1].type).toBe('fail')
})
test('连续失败保留最近一次原因与执行身份', () => {
  const result = rows([execution(23, 'error', { outcome_reason: '行情连接断开' }), execution(22, 'error')])
  expect(result.rows[0]).toMatchObject({ type: 'fail', count: 2, executionId: 'e23', reason: '行情连接断开' })
})
test('部分成交伴随实际错误仍是失败', () => {
  const result = rows([execution(23, 'error', { outcome_reason: '拒单', symbol_results: { A: { outcome: 'completed' }, B: { outcome: 'error' } } })])
  expect(result.rows[0].type).toBe('fail')
})
test('旧记录一律中性保留且不合并', () => {
  const result = rows([execution(23), execution(22, undefined, { status: 'SUCCEEDED', error: '旧错误' })])
  expect(result.rows.map(recentRowText)).toEqual(['历史执行记录', '历史执行记录'])
  expect(result.rows[0]).toMatchObject({ executionId: 'e23' })
})
test('新记录证据缺失显示待确认', () => {
  expect(recentRowText(rows([execution(23, 'unknown')]).rows[0])).toBe('执行结果待确认')
})
test('完成逐条保留，明确 NOOP 可以折叠', () => {
  expect(rows([execution(23, 'completed'), execution(22, 'completed')]).rows).toHaveLength(2)
  expect(rows([execution(23, 'completed', { status: 'NOOP' }), execution(22, 'completed', { status: 'NOOP' })]).rows[0]).toMatchObject({ type: 'noop', count: 2 })
})
test('终止与前置受阻单独分类', () => {
  const result = rows([execution(23, 'terminated'), execution(22, 'blocked', { outcome_reason: '当前不在交易时间' })])
  expect(result.rows.map(recentRowText)).toEqual(['已终止', '未执行 · 当前不在交易时间'])
})
test('窗口拉满才显示饱和，限制折叠后的行数', () => {
  const items = [execution(23, 'not_reached'), execution(22, 'not_reached')]
  expect(rows(items, 6, 2).rows[0]).toMatchObject({ saturated: true })
  expect(rows(items).rows[0]).toMatchObject({ saturated: false })
  expect(rows([execution(23, 'completed'), ...items], 1).truncated).toBe(true)
  expect(rows([]).rows).toEqual([])
})
test('排程跳过与执行相互切断分组', () => {
  const skip: AccountActivity = { kind: 'schedule_skip', id: 1, occurred_at: '2026-09-14T14:00:00', channel: 'ctp', reason_code: 'CALENDAR.CLOSED', calendar_day: '2026-09-14', calendar_id: 'cn', calendar_label: '中国' }
  const result = rows([skip, execution(23, 'not_reached'), { ...skip, id: 2 }])
  expect(result.rows.map(r => r.type)).toEqual(['skip', 'partial', 'skip'])
})
