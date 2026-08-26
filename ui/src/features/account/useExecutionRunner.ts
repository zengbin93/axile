import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getExecutionStatus,
  triggerEmptyPositions,
  triggerExecute,
} from '@/lib/api/executions'
import { ApiError } from '@/lib/api/client'
import { describeRunOutcome, type RunKind } from '@/features/account/runOutcome'
import { useToastStore } from '@/stores/ui'
import type { ExecutionTaskStatus } from '@/types/api'

const TERMINAL: ExecutionTaskStatus[] = ['SUCCEEDED', 'FAILED', 'TERMINATED']

export type { RunKind }

interface RunnerState {
  /** 是否有执行在进行中。 */
  running: boolean
  kind: RunKind | null
  executionId: string | null
}

/**
 * 立即执行 / 清仓的运行器。
 *
 * 点下即乐观 ``running``（状态行/终止钮立刻跟上），HTTP 成功后再写入
 * ``execution_id`` 并轮询终态；触发失败则回滚。后端状态枚举无进度计数，
 * 故 UI 以不定态轮询到 SUCCEEDED/FAILED/TERMINATED 再回调刷新。
 */
export function useExecutionRunner(accountId: number, onSettled?: () => void) {
  const toast = useToastStore((s) => s.toast)
  const [state, setState] = useState<RunnerState>({
    running: false,
    kind: null,
    executionId: null,
  })
  const [error, setError] = useState<Error | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const settledRef = useRef(onSettled)
  settledRef.current = onSettled
  // 防连点：乐观态已进 running 时忽略后续 start（state 闭包会旧，用 ref）。
  const runningRef = useRef(false)

  const stopPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = undefined
  }, [])

  useEffect(() => stopPoll, [stopPoll])

  const start = useCallback(
    async (kind: RunKind) => {
      if (runningRef.current) return
      runningRef.current = true
      setError(null)
      // 乐观进执行：不等 trigger 返回，避免「点了没反应」。
      setState({ running: true, kind, executionId: null })
      try {
        const trigger =
          kind === 'exec'
            ? await triggerExecute(accountId)
            : await triggerEmptyPositions(accountId)
        setState({ running: true, kind, executionId: trigger.execution_id })
        if (trigger.accepted === 'coalesced') toast('已与等待中的执行合并')
        else toast(kind === 'exec' ? '已触发执行…' : '已触发清仓…')

        stopPoll()
        pollRef.current = setInterval(async () => {
          try {
            const st = await getExecutionStatus(trigger.execution_id)
            if (TERMINAL.includes(st.status)) {
              stopPoll()
              runningRef.current = false
              setState({ running: false, kind: null, executionId: null })
              const outcome = describeRunOutcome(kind, st.status, st.output_status, st.error)
              if (outcome.kind === 'failed') setError(new Error(outcome.error))
              else toast(outcome.toast)
              settledRef.current?.()
            }
          } catch (err) {
            if (err instanceof ApiError && err.status === 404) {
              stopPoll()
              runningRef.current = false
              setState({ running: false, kind: null, executionId: null })
              setError(new Error('执行已结束或中断'))
              settledRef.current?.()
            }
          }
        }, 1500)
      } catch (err) {
        runningRef.current = false
        setState({ running: false, kind: null, executionId: null })
        setError(err instanceof Error ? err : new Error(String(err)))
      }
    },
    [accountId, toast, stopPoll],
  )

  return { ...state, error, clearError: () => setError(null), start }
}
