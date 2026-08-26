import { describe, expect, it } from 'bun:test'

import { ApiError } from '@/lib/api/client'
import { errorInfo, isConnectionError, redactErrorText, shortErrorReason } from './errorInfo'

describe('errorInfo', () => {
  it('turns fetch failures into an actionable service message', () => {
    expect(shortErrorReason(new TypeError('Failed to fetch'))).toBe('无法连接 axile 服务')
  })

  it('distinguishes network failures from HTTP and business errors', () => {
    expect(isConnectionError(new TypeError('Failed to fetch'))).toBe(true)
    expect(isConnectionError(new TypeError('Load failed'))).toBe(true)
    expect(isConnectionError(new Error('Failed to fetch'))).toBe(false)
    expect(isConnectionError(new Error('HTTP 503'))).toBe(false)
  })

  it('redacts common secret assignments and URL parameters', () => {
    const value = redactErrorText('password=hunter2 token=abc url=?api_key=xyz&x=1')
    expect(value).not.toContain('hunter2')
    expect(value).not.toContain('abc')
    expect(value).not.toContain('xyz')
  })

  it('exposes only safe ApiError evidence', () => {
    const info = errorInfo(new ApiError(409, '冲突', { code: 'RUNNING', requestId: 'req-2' }))
    expect(info.evidence).toEqual([
      { label: 'HTTP', value: '409' },
      { label: '错误码', value: 'RUNNING' },
      { label: '请求标识', value: 'req-2' },
    ])
  })
})
