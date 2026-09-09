import { expect, test } from 'bun:test'
import { availableAlgorithms, createAlgorithmCatalog } from './algorithmCatalog'
import type { AlgorithmInfo } from '@/types/api'

const algo: AlgorithmInfo = { name: 'CUSTOM', label: '服务端名称', description: '服务端说明', default_params: {}, params_schema: {}, channels: null, slots: null, builtin: false }

test('两槽并发加载去重，失败后重试通知全部订阅者', async () => {
  let requests = 0
  const catalog = createAlgorithmCatalog(async () => {
    if (++requests === 1) throw new Error('offline')
    return [algo]
  })
  const observedA: unknown[] = []
  const observedB: unknown[] = []
  const unsubscribe = catalog.subscribe(() => observedA.push(catalog.getSnapshot()))
  catalog.subscribe(() => observedB.push(catalog.getSnapshot()))
  const first = catalog.load()
  expect(catalog.load()).toBe(first)
  await first
  expect(requests).toBe(1)
  expect(catalog.getSnapshot().error?.message).toBe('offline')
  expect(catalog.getSnapshot().data).toBeNull()
  await catalog.load()
  expect(requests).toBe(2)
  expect(catalog.getSnapshot()).toEqual({ data: [algo], loading: false, error: null })
  expect(observedA).toEqual(observedB)
  unsubscribe()
})

test('成功空清单与失败不同，特种任务和其他渠道不进入账户候选', async () => {
  const catalog = createAlgorithmCatalog(async () => [])
  await catalog.load()
  expect(catalog.getSnapshot()).toEqual({ data: [], loading: false, error: null })
  const list = [algo, { ...algo, name: 'OPTION', slots: [] }, { ...algo, name: 'CTP', channels: ['ctp'] as AlgorithmInfo['channels'] }]
  expect(availableAlgorithms(list, 'gm', 'trade').map((a) => a.name)).toEqual(['CUSTOM'])
  expect(availableAlgorithms(list, 'ctp', 'empty').map((a) => a.name)).toEqual(['CUSTOM', 'CTP'])
})
