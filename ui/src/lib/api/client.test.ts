import { describe, expect, it } from 'bun:test'

import { ApiError, apiErrorFromBody } from './client'

describe('apiErrorFromBody', () => {
  it('preserves safe structured diagnostics', () => {
    const error = apiErrorFromBody(409, 'Conflict', {
      message: '账户正在执行', code: 'EXECUTION_RUNNING', request_id: 'req-1',
      details: { password: 'must-not-be-retained' },
    })
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('账户正在执行')
    expect(error.code).toBe('EXECUTION_RUNNING')
    expect(error.requestId).toBe('req-1')
    expect(JSON.stringify(error)).not.toContain('must-not-be-retained')
  })

  it('formats validation issues without retaining their input', () => {
    const error = apiErrorFromBody(422, 'Unprocessable Entity', {
      detail: [{ loc: ['body', 'cron_expr'], msg: 'Field required', input: 'secret-value' }],
      body: { api_key: 'secret-value' },
    })
    expect(error.message).toBe('cron_expr：Field required')
    expect(JSON.stringify(error)).not.toContain('secret-value')
  })

  it('falls back to an HTTP label when the response is not JSON', () => {
    expect(apiErrorFromBody(503, '', null).message).toBe('HTTP 503')
  })
})
