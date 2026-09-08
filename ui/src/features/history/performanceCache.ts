import { getPerformanceSnapshot, refreshPerformance, type PerformanceRange, type PerformanceSnapshot } from '@/lib/api/performance'

interface State { data: PerformanceSnapshot | null; error: Error | null; checking: boolean }
interface Entry { state: State; listeners: Set<() => void>; flight?: Promise<void> }
const entries = new Map<string, Entry>()
const refreshes = new Map<number, Promise<boolean>>()
const keyOf = (id: number, range: PerformanceRange) => `${id}:${range}`

export function performanceEntry(id: number, range: PerformanceRange): Entry {
  const key = keyOf(id, range)
  let entry = entries.get(key)
  if (!entry) { entry = { state: { data: null, error: null, checking: false }, listeners: new Set() }; entries.set(key, entry) }
  return entry
}
function publish(entry: Entry, state: State) {
  entry.state = state
  entry.listeners.forEach(listener => listener())
}
export function checkPerformance(id: number, range: PerformanceRange): Promise<void> {
  const entry = performanceEntry(id, range)
  if (entry.flight) return entry.flight
  publish(entry, { ...entry.state, checking: true })
  entry.flight = (async () => {
    try {
      let data = await getPerformanceSnapshot(id, range)
      const old = entry.state.data
      // Preserve chart identity when only queue status or retry metadata changed.
      if (data.snapshot_id && data.snapshot_id === old?.snapshot_id) data = { ...data, result: old.result, daily_costs: old.daily_costs, events: old.events }
      publish(entry, { data, error: null, checking: false })
    } catch (error) {
      publish(entry, { ...entry.state, error: error instanceof Error ? error : new Error(String(error)), checking: false })
    } finally { entry.flight = undefined }
  })()
  return entry.flight
}
export function requestPerformanceRefresh(id: number): Promise<boolean> {
  const existing = refreshes.get(id)
  if (existing) return existing
  const flight = (async () => {
    try {
      await refreshPerformance(id)
      const matching = [...entries].filter(([key]) => key.startsWith(`${id}:`))
      await Promise.all(matching.map(async ([key, entry]) => {
        await entry.flight
        if (entry.state.data) publish(entry, { ...entry.state, data: { ...entry.state.data, status: entry.state.data.result ? 'stale' : 'pending', error: null } })
        await checkPerformance(id, key.split(':')[1] as PerformanceRange)
      }))
      return true
    } catch (error) {
      for (const [key, entry] of entries) if (key.startsWith(`${id}:`)) publish(entry, { ...entry.state, error: error instanceof Error ? error : new Error(String(error)) })
      return false
    } finally { refreshes.delete(id) }
  })()
  refreshes.set(id, flight)
  return flight
}
export const snapshotPending = (data: PerformanceSnapshot | null) => data?.status === 'pending' || data?.status === 'stale' || (data?.status === 'failed' && data.retry_at != null)

/** 仪表盘发现新版时更新已订阅的绩效页。 */
export function reconcilePerformanceVersion(id: number, snapshotId: string | null) {
  for (const [key, entry] of entries) {
    if (key.startsWith(`${id}:`) && entry.listeners.size && entry.state.data?.snapshot_id !== snapshotId) {
      void checkPerformance(id, key.split(':')[1] as PerformanceRange)
    }
  }
}
