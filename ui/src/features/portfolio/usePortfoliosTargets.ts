import { useEffect, useState } from 'react'
import { getPortfolioTargetSnapshot } from '@/lib/api/portfolios'
import type { TargetWeightSnapshot } from '@/types/api'

/** 单个组合目标快照的取数状态（页面层一份数据，同时喂卡片与页头摘要）。 */
export interface PortfolioTargetFetch {
  loading: boolean
  snapshot: TargetWeightSnapshot | null
  error: Error | null
}

/**
 * 页面层统一拉取所有组合的目标快照。
 *
 * 卡片不再各自为政：同一 fetch 结果派生卡片目标态与页头摘要判词，避免「卡片说有问题、
 * 页头报全部到位」的信息分裂。组合增删时按 id 集合重建请求，卸载即中止。
 */
export function usePortfoliosTargets(portfolioIds: (number | null | undefined)[]): Record<number, PortfolioTargetFetch> {
  const key = portfolioIds.filter((id): id is number => id != null).join(',')
  const [states, setStates] = useState<Record<number, PortfolioTargetFetch>>({})

  useEffect(() => {
    const ids = key === '' ? [] : key.split(',').map(Number)
    if (ids.length === 0) {
      setStates({})
      return
    }
    const controllers = new Map<number, AbortController>()
    // 先一次性置 loading；保留旧快照避免卡片闪空（与轮询 hook 的「后台刷新保留上次成功值」同语义）。
    setStates((prev) =>
      Object.fromEntries(ids.map((id) => [id, { loading: true, snapshot: prev[id]?.snapshot ?? null, error: null }])),
    )
    for (const id of ids) {
      const controller = new AbortController()
      controllers.set(id, controller)
      getPortfolioTargetSnapshot(id, controller.signal)
        .then((snapshot) => {
          if (controller.signal.aborted) return
          setStates((prev) => ({ ...prev, [id]: { loading: false, snapshot, error: null } }))
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          setStates((prev) => ({
            ...prev,
            [id]: { loading: false, snapshot: null, error: error instanceof Error ? error : new Error(String(error)) },
          }))
        })
    }
    return () => {
      for (const controller of controllers.values()) controller.abort()
    }
  }, [key])

  return states
}
