import { afterEach, describe, expect, it, test } from 'bun:test'

import { initStatus, peekInitValues, saveExecutionAlert, initSavePayload, initValuesFromStatus } from './init'

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
          sqlalchemy_database_configured: true,
          exe_err_feishu_configured: true,
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

const values = initValuesFromStatus({ sqlalchemy_database_configured: true, exe_err_feishu_configured: true, environment: 'local', app_log_dir: './logs', axile_log_rotation: '1 day', algorithm_modules: [], algorithm_directories: [] })
test('仅修改高级配置不提交隐藏凭证或默认数据库', () => {
  const payload = JSON.parse(JSON.stringify(initSavePayload({ ...values, app_log_dir: './new-logs' }, true)))
  expect(payload.app_log_dir).toBe('./new-logs')
  expect(payload).not.toHaveProperty('sqlalchemy_database_uri')
  expect(payload).not.toHaveProperty('exe_err_feishu_key')
})
test('新数据库地址可以替换，首启仍提交完整配置', () => {
  expect(initSavePayload({ ...values, sqlalchemy_database_uri: 'sqlite+aiosqlite:///new.db' }, true).sqlalchemy_database_uri).toBe('sqlite+aiosqlite:///new.db')
  expect(initSavePayload(values, false).exe_err_feishu_key).toBe('')
})
