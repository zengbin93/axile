import { afterEach, describe, expect, it } from 'bun:test'

import { initStatus, peekInitValues, saveExecutionAlert } from './init'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('saveExecutionAlert', () => {
  it('使用 PATCH 保存并同步更新配置缓存', async () => {
    const requests: Array<{ input: string; init?: RequestInit }> = []
    const responses = [
      {
        configured: true,
        environment: 'local',
        values: {
          sqlalchemy_database_uri: 'sqlite+aiosqlite:///./axile.db',
          exe_err_feishu_key: 'old-key',
          environment: 'local',
          app_log_dir: './logs',
          axile_log_rotation: '1 day',
          algorithm_modules: [],
          algorithm_directories: [],
        },
      },
      { ok: true, message: '执行告警配置已保存并立即生效。' },
    ]
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      requests.push({ input: String(input), init })
      return Response.json(responses.shift())
    }) as typeof fetch

    await initStatus()
    const result = await saveExecutionAlert('new-key')

    expect(result.ok).toBeTrue()
    expect(requests[1]?.input).toBe('/api/v1/init/execution-alert')
    expect(requests[1]?.init?.method).toBe('PATCH')
    expect(requests[1]?.init?.body).toBe(JSON.stringify({ exe_err_feishu_key: 'new-key' }))
    expect(peekInitValues()?.exe_err_feishu_key).toBe('new-key')
  })
})
