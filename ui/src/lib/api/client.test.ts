import { describe, expect, it } from 'bun:test'

import { ApiError, apiErrorFromBody, apiGet, apiUpload } from './client'

const LEGACY_PASSWORD_HEADER = ['x', 'api', 'password'].join('-')

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

describe('API requests', () => {
  it('does not send a password header for JSON requests', async () => {
    const originalFetch = globalThis.fetch
    let request: RequestInit | undefined
    globalThis.fetch = ((_input: string, init?: RequestInit) => {
      request = init
      return Promise.resolve(new Response('{}'))
    }) as typeof fetch

    try {
      await apiGet('/status')
    } finally {
      globalThis.fetch = originalFetch
    }

    expect(new Headers(request?.headers).has(LEGACY_PASSWORD_HEADER)).toBe(false)
  })

  it('does not send a password header for multipart uploads', async () => {
    const originalFetch = globalThis.fetch
    let request: RequestInit | undefined
    globalThis.fetch = ((_input: string, init?: RequestInit) => {
      request = init
      return Promise.resolve(new Response('{}'))
    }) as typeof fetch

    try {
      await apiUpload('/upload', new File(['test'], 'test.txt'))
    } finally {
      globalThis.fetch = originalFetch
    }

    expect(new Headers(request?.headers).has(LEGACY_PASSWORD_HEADER)).toBe(false)
  })
})
