import { expect, test } from 'bun:test'
import { executionOutcome } from './executionOutcome'
import { describeRunOutcome } from './runOutcome'

test('只接受明确结论，旧状态和错误文本都不推断成败', () => {
  for (const raw of [{}, { status: 'FAILED', error: '断开', is_success: 0 }, { status: 'SUCCEEDED' }, { outcome: 'invalid' }]) {
    expect(executionOutcome(raw)).toMatchObject({ outcome: 'legacy', text: '历史执行记录', warning: false })
  }
})
test('摘要最多显示三个未到位品种，不包含已完成品种', () => {
  const view = executionOutcome({ outcome: 'not_reached', symbol_results: { A: { outcome: 'completed' }, B: { outcome: 'not_reached' }, C: { outcome: 'not_reached' }, D: { outcome: 'blocked' }, E: { outcome: 'not_reached' } } })
  expect(view.text).toBe('执行不到位 · B、C、D 等 4 个品种')
  expect(view.symbols).toEqual(['B', 'C', 'D', 'E'])
})
test('清仓只使用本次结论，完成保持中性', () => {
  expect(executionOutcome({ outcome: 'completed', execution_kind: 'clear_positions', status: 'FAILED' })).toMatchObject({ text: '清仓完成', warning: false })
})
test('结束提示与概览结论一致，即使任务因旧控制口径标记 FAILED', () => {
  const payload = { outcome: 'not_reached', outcome_symbols: ['m2701'] }
  expect(describeRunOutcome('exec', payload)).toEqual({ kind: 'not_reached', toast: executionOutcome(payload).text })
})

test('账户结论和结束提示直接展示后端原因', () => {
  const raw = Object.freeze({ outcome: 'blocked' as const, outcome_reason: '非交易时段' })
  expect(executionOutcome(raw).text).toBe('未执行 · 非交易时段')
  expect(describeRunOutcome('exec', raw)).toEqual({ kind: 'blocked', toast: '未执行 · 非交易时段' })
  expect(raw.outcome_reason).toBe('非交易时段')
  expect(executionOutcome({ outcome: 'blocked', outcome_reason: ' ' }).text).toBe('未执行')
})

test('前端不翻译历史原因码', () => {
  for (const reason of ['CLOSED', 'CALENDAR_UNAVAILABLE', 'QUOTE_TRADING_TIME_UNAVAILABLE']) {
    expect(executionOutcome({ outcome: 'blocked', outcome_reason: reason }).text).toBe('未执行 · ' + reason)
  }
})
