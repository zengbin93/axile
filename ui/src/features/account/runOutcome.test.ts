import { expect, test } from 'bun:test'
import { describeRunOutcome } from './runOutcome'

test('FAILED + BLOCKED → 非交易时段 toast，不当成操作失败', () => {
  const outcome = describeRunOutcome('exec', 'FAILED', 'BLOCKED', '5 个品种因交易时段不可执行')
  expect(outcome).toEqual({ kind: 'blocked', toast: '非交易时段，未下单' })
})

test('FAILED 使用服务端 error，缺省才兜底，不弹 toast', () => {
  expect(describeRunOutcome('exec', 'FAILED', null, 'CTP 断线').kind).toBe('failed')
  expect(describeRunOutcome('exec', 'FAILED', null, 'CTP 断线')).toMatchObject({ error: 'CTP 断线' })
  expect(describeRunOutcome('exec', 'FAILED', null, null)).toMatchObject({
    error: '执行失败，服务端未返回原因',
  })
  expect('toast' in describeRunOutcome('exec', 'FAILED', 'PARTIAL', '4 个品种执行未成功')).toBe(false)
})

test('SUCCEEDED 普通调仓仍说已到位', () => {
  expect(describeRunOutcome('exec', 'SUCCEEDED', 'SUCCEEDED', null)).toEqual({
    kind: 'success',
    toast: '执行完成 · 已按目标到位',
  })
})

test('TERMINATED 与清仓成功各自一句', () => {
  expect(describeRunOutcome('exec', 'TERMINATED', null, null)).toEqual({
    kind: 'terminated',
    toast: '执行已终止',
  })
  expect(describeRunOutcome('clear', 'SUCCEEDED', 'SUCCEEDED', null)).toEqual({
    kind: 'success',
    toast: '已清仓',
  })
})
