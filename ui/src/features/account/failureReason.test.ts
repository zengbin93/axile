import { expect, test } from 'bun:test'
import { describeFailure, describeFailureText } from './failureReason'
import type { ExecutionEvent } from '../../types/api'

/** 造一条 execution_failed 事件；error 可为裸串或 worker 对象。 */
function failEvent(error: unknown, over: Partial<ExecutionEvent> = {}): ExecutionEvent {
  return {
    id: 1,
    execution_id: 'e1',
    account_id: 1,
    channel: 'paper',
    algorithm: 'single_maker',
    event_type: 'execution_failed',
    status: 'ERROR',
    reason_family: 'SYSTEM',
    reason_code: 'COMMON.EXECUTION_FAILED',
    symbol: null,
    order_id: null,
    client_order_id: null,
    ts_local_created: '2026-07-21T12:53:24',
    seq: 0,
    details: { debug: { error } },
    ...over,
  }
}

test('-1021 时钟噪声刻意不翻译 → 未归类、保留原文（该在源头修，不在产品里美化）', () => {
  const raw = '(-1021, "Timestamp for this request was 1000ms ahead of the server\'s time.")'
  const f = describeFailure(failEvent(raw))
  expect(f?.category).toBe('未归类')
  expect(f?.raw).toBe(raw)
})

test('worker 对象形态也能翻（读 message，且后端 retryable 优先于签名表）', () => {
  const f = describeFailure(failEvent({ type: 'bad_request_error', message: '-2019 margin is insufficient', retryable: true }))
  expect(f?.category).toBe('保证金不足')
  // 签名表默认 retryable=false，被后端明确的 retryable=true 覆盖。
  expect(f?.retryable).toBe(true)
})

test('API Key 无效 → 密钥/权限 · 归账户 · 不可重试', () => {
  const f = describeFailure(failEvent('(-2015, "Invalid API-key, IP, or permissions for action.")'))
  expect(f?.category).toBe('密钥/权限')
  expect(f?.blame).toBe('account')
  expect(f?.retryable).toBe(false)
})

test('保证金不足 → 归账户', () => {
  expect(describeFailure(failEvent('(-2019, "Margin is insufficient.")'))?.category).toBe('保证金不足')
})

test('认不出的错 → 未归类兜底，保留原文', () => {
  const f = describeFailure(failEvent('some weird unmapped error'))
  expect(f?.category).toBe('未归类')
  expect(f?.raw).toBe('some weird unmapped error')
})

test('无事件 → null', () => {
  expect(describeFailure(null)).toBeNull()
})

test('状态接口的 CTP 4097 → CTP 连接，可在恢复后重试', () => {
  const f = describeFailureText('调仓执行失败, 错误原因: CTP 交易前置断线: 4097')
  expect(f.category).toBe('CTP 连接')
  expect(f.human).toBe('CTP 交易前置已断开')
  expect(f.retryable).toBe(true)
})

test('GM token 状态码 1000 → GM 凭证 · 归账户 · 不可直接重试', () => {
  const f = describeFailureText('gm_authentication_error: {"status": 1000, "message": "错误或无效的token"}')
  expect(f.category).toBe('GM 凭证')
  expect(f.human).toBe('GM token 无效或已失效')
  expect(f.blame).toBe('account')
  expect(f.retryable).toBe(false)
})
