import { useCallback, useState } from 'react'
import { usePolling } from '@/lib/hooks/usePolling'
import type { TargetWeightSnapshot } from '@/types/api'

/** 把只读快照加载与会执行用户代码的主动重算分成两个明确动作。 */
export function useTargetSnapshot(
  reader: (signal: AbortSignal) => Promise<TargetWeightSnapshot>,
  recalculator: () => Promise<TargetWeightSnapshot>,
  queryKey: string,
  enabled = true,
) {
  const snapshot = usePolling(reader, { queryKey, intervalMs: 0, enabled })
  const reloadSnapshot = snapshot.refresh
  const [recalculating, setRecalculating] = useState(false)
  const [recalculateError, setRecalculateError] = useState<Error | null>(null)

  const recalculate = useCallback(async () => {
    if (!enabled || recalculating) return
    setRecalculating(true)
    setRecalculateError(null)
    try {
      await recalculator()
      await reloadSnapshot()
    } catch (error) {
      setRecalculateError(error instanceof Error ? error : new Error(String(error)))
    } finally {
      setRecalculating(false)
    }
  }, [enabled, recalculating, recalculator, reloadSnapshot])

  return {
    ...snapshot,
    recalculating,
    recalculateError,
    recalculate,
    reloadSnapshot,
  }
}
