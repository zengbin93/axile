import { expect, test } from 'bun:test'
import { describeFailure, describeFailureText } from './failureReason'
import type { ExecutionEvent } from '@/types/api'

test.each(['-2019 Margin is insufficient', 'CTP 交易前置断线: 4097', '{"status":1000}', 'CLOSED', ''])('错误原文直接回放，不分类或建议重试：%s', raw => {
  expect(describeFailureText(raw)).toEqual({ human: raw, raw })
})
test('事件只回放明确 message', () => {
  const event = { details: { debug: { error: { message: '原始错误', retryable: true } } } } as unknown as ExecutionEvent
  expect(describeFailure(event)).toEqual({ human: '原始错误', raw: '原始错误' })
  expect(describeFailure(null)).toBeNull()
})
