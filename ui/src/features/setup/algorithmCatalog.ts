import { getAlgorithms } from '@/lib/api/system'
import { registerAlgorithmLabels } from '@/features/setup/algorithms'
import type { AlgorithmInfo } from '@/types/api'

export interface AlgorithmCatalogState {
  data: AlgorithmInfo[] | null
  loading: boolean
  error: Error | null
}

/** 两个槽位订阅同一请求；失败后释放 Promise，重试不改变账户草稿。 */
export function createAlgorithmCatalog(fetcher: () => Promise<AlgorithmInfo[]>) {
  let state: AlgorithmCatalogState = { data: null, loading: false, error: null }
  let pending: Promise<void> | null = null
  const listeners = new Set<() => void>()
  const publish = (next: AlgorithmCatalogState) => {
    state = next
    listeners.forEach((listener) => listener())
  }
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    load: () => {
      if (pending) return pending
      // Promise 微任务启动请求，保证通知订阅者前已设置 pending。
      pending = Promise.resolve().then(fetcher).then(
        (data) => {
          registerAlgorithmLabels(data)
          publish({ data, loading: false, error: null })
        },
        (error: unknown) => publish({ ...state, loading: false, error: error instanceof Error ? error : new Error(String(error)) }),
      ).finally(() => { pending = null })
      publish({ ...state, loading: true, error: null })
      return pending
    },
  }
}

export const algorithmCatalog = createAlgorithmCatalog(() => getAlgorithms())

export function availableAlgorithms(algorithms: AlgorithmInfo[], channel: string, slot: string) {
  return algorithms.filter((algo) =>
    (algo.channels === null || algo.channels.some((item) => item === channel)) &&
    (algo.slots === null || algo.slots.some((item) => item === slot)),
  )
}
