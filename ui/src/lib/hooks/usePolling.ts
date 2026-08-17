import { useCallback, useEffect, useRef, useState } from 'react'

/** 轮询状态机。`data` 保留上一次成功值，失联时用于降级展示。 */
export interface PollingState<T> {
  data: T | null
  error: Error | null
  /** 首次加载中（尚无任何数据）。 */
  loading: boolean
  /** 最近一次成功的时间戳（ms），供「数据 N 秒前」展示。 */
  updatedAt: number | null
  /** 手动触发一次刷新。 */
  refresh: () => void
}

/**
 * 轮询一个异步取数函数，按 `intervalMs` 周期刷新。
 *
 * - 保留上一次成功数据：请求失败时 `data` 不清空，仅置 `error`（失联降级）。
 * - 组件卸载 / 依赖变化时中止在途请求。
 * - `intervalMs <= 0` 时只取一次、不轮询。
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs = 5000,
  /** 变化时重新取数（用于依赖上游数据的联动请求）。 */
  resetKey?: unknown,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)

  // fetcher 每次渲染都是新引用；用 ref 固定，避免把它放进 effect 依赖。
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    const run = async () => {
      try {
        const result = await fetcherRef.current(controller.signal)
        if (cancelled) return
        setData(result)
        setError(null)
        setUpdatedAt(Date.now())
      } catch (err) {
        if (cancelled || controller.signal.aborted) return
        setError(err instanceof Error ? err : new Error(String(err)))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void run()
    const timer =
      intervalMs > 0 ? setInterval(() => void run(), intervalMs) : undefined

    return () => {
      cancelled = true
      controller.abort()
      if (timer) clearInterval(timer)
    }
  }, [intervalMs, tick, resetKey])

  return { data, error, loading, updatedAt, refresh }
}
