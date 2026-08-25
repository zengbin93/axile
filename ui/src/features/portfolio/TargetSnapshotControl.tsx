import { RefreshCw } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { Tooltip } from '@/components/ui/Tooltip'
import { targetSnapshotText } from '@/features/portfolio/targetSnapshotDisplay'
import type { TargetWeightSnapshot } from '@/types/api'

export function TargetSnapshotControl({
  snapshot,
  loading = false,
  recalculating,
  error,
  disabled = false,
  disabledReason,
  contextName,
  onRecalculate,
}: {
  snapshot: TargetWeightSnapshot | null
  loading?: boolean
  recalculating: boolean
  error: Error | null
  disabled?: boolean
  disabledReason?: string
  contextName?: string | null
  onRecalculate: () => void
}) {
  const tooltip = disabledReason ?? (recalculating ? '正在重新计算目标权重' : '重新计算当前目标权重')
  const meta = loading && !snapshot
    ? '正在读取目标权重…'
    : error && snapshot?.calculated_at
      ? `本次计算失败 · ${targetSnapshotText(snapshot, contextName)}`
      : targetSnapshotText(snapshot, contextName)

  return (
    <div>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div title={meta} className={`min-w-0 text-[12.5px] ${error ? 'text-warn' : 'text-ink-3'}`}>
          <InkRewrite text={meta} tone="label" />
        </div>
        <Tooltip content={tooltip}>
          <span className="inline-flex flex-none">
            <button
              type="button"
              onClick={onRecalculate}
              disabled={disabled || loading || recalculating}
              aria-label={recalculating ? '正在重新计算目标权重' : '重新计算当前目标权重'}
              className="grid h-6 w-6 cursor-pointer place-items-center rounded-md text-ink-3 hover:bg-fill hover:text-ink-1 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <RefreshCw size={14} className={recalculating ? 'animate-spin motion-reduce:animate-none' : undefined} />
            </button>
          </span>
        </Tooltip>
      </div>
      {error && !snapshot?.calculated_at && (
        <p className="mt-1.5 text-[12.5px] text-warn">目标权重计算失败：{error.message}</p>
      )}
    </div>
  )
}
