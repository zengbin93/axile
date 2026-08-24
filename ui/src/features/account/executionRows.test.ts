import { describe, it, expect } from 'bun:test'

import { lifecycleNotes, symbolRows } from './executionRows'
import type { ExecutionEvent } from '@/types/api'

/** 造一条最小可用的执行事件。 */
function ev(patch: Partial<ExecutionEvent>): ExecutionEvent {
  return {
    event_type: 'symbol_decision_made',
    status: 'INFO',
    reason_code: '',
    symbol: null,
    details: {},
    ...patch,
  } as ExecutionEvent
}

describe('symbolRows', () => {
  it('只挑逐只决策/跳过事件，忽略生命周期事件', () => {
    const rows = symbolRows([
      ev({ event_type: 'execution_started', symbol: null }),
      ev({ event_type: 'symbol_decision_made', symbol: 'rb2610', status: 'SUCCESS' }),
    ])
    expect(rows).toEqual([{ symbol: 'rb2610', status: 'SUCCESS', reason: '' }])
  })

  it('失败事件把 details.debug.error 作为原因显出', () => {
    const rows = symbolRows([
      ev({
        event_type: 'symbol_decision_made',
        symbol: 'ag2612',
        status: 'ERROR',
        details: { debug: { error: "'dict' object has no attribute 'max_wait_seconds'" } },
      }),
    ])
    expect(rows[0]?.status).toBe('ERROR')
    expect(rows[0]?.reason).toContain('max_wait_seconds')
  })

  it('普通跳过不把内部 reason_code 暴露为原因', () => {
    const rows = symbolRows([ev({ event_type: 'symbol_skipped', symbol: 'au2612', reason_code: 'COMMON.SYMBOL_SKIPPED' })])
    expect(rows[0]?.reason).toBe('')
  })

  it('具体跳过原因显示中文，未知代码使用中性兜底', () => {
    const rows = symbolRows([
      ev({ event_type: 'symbol_skipped', symbol: 'au2612', reason_code: 'COMMON.SUB_MIN_QTY' }),
      ev({ event_type: 'symbol_skipped', symbol: 'rb2610', reason_code: 'PLUGIN.UNKNOWN_REASON' }),
    ])
    expect(rows.map((row) => row.reason)).toEqual(['数量取整后不足最小下单量', '未执行'])
  })
})

describe('lifecycleNotes', () => {
  it('取出 EXECUTION_FAILED 的错误原因', () => {
    const notes = lifecycleNotes([
      ev({ event_type: 'execution_started', status: 'INFO' }),
      ev({
        event_type: 'execution_failed',
        status: 'ERROR',
        details: { debug: { error: "算法 'SINGLE-MAKER' 的参数非法: max_wait_seconds …" } },
      }),
    ])
    expect(notes).toHaveLength(1)
    expect(notes[0]?.status).toBe('ERROR')
    expect(notes[0]?.text).toContain('参数非法')
  })

  it('排除逐只事件，避免与 symbolRows 重复', () => {
    const notes = lifecycleNotes([
      ev({ event_type: 'symbol_decision_made', symbol: 'ag2612', status: 'ERROR', details: { debug: { error: 'x' } } }),
    ])
    expect(notes).toHaveLength(0)
  })
})
