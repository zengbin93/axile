import { expect, test } from 'bun:test'
import { describeFailureText } from './failureReason'

test.each(['-2019 Margin is insufficient', 'CTP 交易前置断线: 4097', '{"status":1000}', 'CLOSED', ''])(
  '错误原文直接回放，不分类或建议重试：%s',
  raw => {
    expect(describeFailureText(raw)).toEqual({ human: raw, raw })
  },
)
