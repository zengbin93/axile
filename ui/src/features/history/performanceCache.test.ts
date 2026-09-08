import { afterEach, expect, test } from 'bun:test'
import { checkPerformance, performanceEntry, requestPerformanceRefresh, snapshotPending, reconcilePerformanceVersion } from './performanceCache'
import type { PerformanceSnapshot } from '@/lib/api/performance'
import { summarizeCosts } from './costs'

const originalFetch = globalThis.fetch
const mockFetch = (implementation: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) => { globalThis.fetch = Object.assign(implementation, { preconnect: originalFetch.preconnect }) }
afterEach(() => { globalThis.fetch = originalFetch })
const snapshot = (changes: Partial<PerformanceSnapshot> = {}) => ({ status: 'ready', snapshot_id: 'batch-1', result: { points: [] }, daily_costs: {}, events: [], error: null, ...changes }) as PerformanceSnapshot

test('simultaneous readers share a request and cached chart references survive status checks', async () => {
  let calls = 0
  let release!: () => void
  mockFetch(async () => { calls++; await new Promise<void>(resolve => { release = resolve }); return Response.json(snapshot()) })
  const first = checkPerformance(800, 'all'), second = checkPerformance(800, 'all')
  expect(first).toBe(second)
  release(); await first
  const cached = performanceEntry(800, 'all').state.data
  mockFetch(async () => { calls++; return Response.json(snapshot({ status: 'stale' })) })
  await checkPerformance(800, 'all')
  const next = performanceEntry(800, 'all').state.data
  expect(calls).toBe(2)
  expect(next?.result).toBe(cached?.result)
  expect(next?.daily_costs).toBe(cached?.daily_costs)
  expect(snapshotPending(next)).toBe(true)
})

test('failed checks retain the successful batch and ranges never borrow another range', async () => {
  mockFetch(async () => Response.json(snapshot()))
  await checkPerformance(801, '30')
  const old = performanceEntry(801, '30').state.data
  mockFetch(async () => { throw new Error('offline') })
  await checkPerformance(801, '30')
  expect(performanceEntry(801, '30').state.data).toBe(old)
  expect(performanceEntry(801, '30').state.error?.message).toBe('offline')
  expect(performanceEntry(801, 'all').state.data).toBeNull()
})

test('manual refresh coalesces POST and replaces curves and costs together', async () => {
  mockFetch(async () => Response.json(snapshot()))
  await checkPerformance(802, 'all')
  let posts = 0
  mockFetch(async (_input, init) => {
    if (init?.method === 'POST') { posts++; return Response.json({ status: 'pending' }) }
    return Response.json(snapshot({ snapshot_id: 'batch-2', daily_costs: { new: summarizeCosts([]) } }))
  })
  await Promise.all([requestPerformanceRefresh(802), requestPerformanceRefresh(802)])
  expect(posts).toBe(1)
  expect(performanceEntry(802, 'all').state.data?.snapshot_id).toBe('batch-2')
  expect(performanceEntry(802, 'all').state.data?.daily_costs).toHaveProperty('new')
  expect(snapshotPending(snapshot({ status: 'failed', retry_at: null }))).toBe(false)
  expect(snapshotPending(snapshot({ status: 'failed', retry_at: 123 }))).toBe(true)
})

test('dashboard publication refreshes subscribed ranges and failure is reported to card caller', async () => {
  mockFetch(async () => Response.json(snapshot()))
  await checkPerformance(803, 'all')
  const entry = performanceEntry(803, 'all')
  const listener = () => {}
  entry.listeners.add(listener)
  let gets = 0
  mockFetch(async () => { gets++; return Response.json(snapshot({ snapshot_id: 'batch-2' })) })
  reconcilePerformanceVersion(803, 'batch-2')
  await entry.flight
  expect(gets).toBe(1)
  expect(entry.state.data?.snapshot_id).toBe('batch-2')
  reconcilePerformanceVersion(803, 'batch-2')
  expect(gets).toBe(1)
  entry.listeners.delete(listener)
  mockFetch(async () => { throw new Error('offline') })
  expect(await requestPerformanceRefresh(803)).toBe(false)
  expect(entry.state.data?.snapshot_id).toBe('batch-2')
  expect(entry.state.error?.message).toBe('offline')
})
