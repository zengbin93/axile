import { expect, test } from 'bun:test'
import { describeRunOutcome } from './runOutcome'

test('明确错误才提示失败', () => {
  expect(describeRunOutcome('exec', { outcome: 'error', outcome_reason: '连接断开' })).toEqual({ kind: 'failed', error: '执行失败 · 连接断开' })
})
test('完成、清仓、终止、受阻分别表达', () => {
  for (const [outcome, text] of [['completed', '执行完成'], ['terminated', '执行已终止'], ['blocked', '未执行'], ['unknown', '执行结果待确认']]) {
    expect(describeRunOutcome('exec', { outcome })).toHaveProperty('toast', text)
  }
  expect(describeRunOutcome('clear', { outcome: 'completed' })).toEqual({ kind: 'success', toast: '清仓完成' })
})
test('旧结果不根据任务状态翻译成败', () => {
  expect(describeRunOutcome('exec', {})).toEqual({ kind: 'unknown', toast: '历史执行记录' })
})
