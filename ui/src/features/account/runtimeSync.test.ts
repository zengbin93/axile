import { expect, test } from 'bun:test'
import { parseAccountRuntimeSync } from '@/lib/api/accounts'
import { newerRuntimeSync, runtimeSyncMessage } from './useAccountRuntimeSync'
import type { AccountRuntimeSync } from '@/types/api'

const sync: AccountRuntimeSync = { status: 'synchronized', revision: 3, attempts: 1, last_error: null, last_attempt_at: null, synchronized_at: null }

test('首次同步的 202 detail 不是同步成功', () => {
  expect(parseAccountRuntimeSync({ detail: '账户运行态尚待首次同步' })).toBeNull()
  expect(runtimeSyncMessage(undefined)).toBe('配置已保存，同步状态暂不可用')
  expect(() => parseAccountRuntimeSync({ status: 'synchronized' })).toThrow()
})

test('保存与同步状态分别表达，旧 revision 不覆盖新保存', () => {
  expect(runtimeSyncMessage(sync)).toBe('算法配置已保存')
  expect(runtimeSyncMessage({ ...sync, status: 'pending' })).toContain('配置已保存，运行态待同步')
  expect(runtimeSyncMessage({ ...sync, status: 'failed' })).toContain('配置已保存，运行态同步失败')
  expect(newerRuntimeSync(sync, { ...sync, revision: 2, status: 'failed' })).toBe(sync)
  expect(newerRuntimeSync(sync, null)).toBe(sync)
  expect(newerRuntimeSync(sync, { ...sync, revision: 4, status: 'pending' })?.revision).toBe(4)
})
