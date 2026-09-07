import { expect, test } from 'bun:test'
import { performanceEvents } from './events'
import { shanghaiTime } from './costs'
import type { PortfolioAccountRecord } from '@/types/api'

test('跨年事件按上海时间倒序，按绩效边界过滤，组合使用当前名称与编号回退', () => {
  const bindings = [
    { created_at: '2025-12-31T16:01:00Z', portfolio_id: 1 },
    { created_at: '2025-12-31T23:59:00', portfolio_id: 2 },
    { created_at: '2026-01-01T00:02:00', portfolio_id: 3 },
    { created_at: '2026-01-02T00:00:00', portfolio_id: null },
  ] as PortfolioAccountRecord[]
  const events = performanceEvents(bindings, [], { start: shanghaiTime('2026-01-01T00:00:00'), end: shanghaiTime('2026-01-02T00:00:00') }, new Map([[1, '当前组合名称']]))
  expect(events.map(e => e.text)).toEqual(['组合 #3', '当前组合名称'])
})
