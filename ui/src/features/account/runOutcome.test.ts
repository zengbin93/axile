import { expect, test } from 'bun:test'
import { describeRunOutcome } from './runOutcome'

test('明确错误才提示失败', () => {
  expect(describeRunOutcome('exec', { status: 'FAILED', error: '连接断开' })).toEqual({ kind: 'failed', error: '执行失败' })
})
test('完成、清仓、终止、受阻分别表达', () => {
  for (const [status, text] of [['SUCCEEDED', '调仓完成'], ['TERMINATED', '执行已终止'], ['BLOCKED', '未执行'], ['UNKNOWN', '执行状态未知']]) {
    expect(describeRunOutcome('exec', { status })).toHaveProperty('toast', text)
  }
  expect(describeRunOutcome('clear', { status: 'SUCCEEDED' })).toEqual({ kind: 'success', toast: '清仓完成' })
})
test('旧结果不根据任务状态翻译成败', () => {
  expect(describeRunOutcome('exec', {})).toEqual({ kind: 'unknown', toast: '执行状态未知' })
})
