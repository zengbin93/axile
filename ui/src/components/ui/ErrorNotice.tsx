import { useEffect, useId, useMemo, useState } from 'react'
import { RefreshCw, TriangleAlert } from 'lucide-react'

import { InkRewrite } from '@/components/ui/InkRewrite'
import { Tooltip } from '@/components/ui/Tooltip'
import { errorInfo, type ErrorEvidence, type ErrorInfo } from '@/lib/errorInfo'
import { timeAgo } from '@/lib/format'

export type ErrorNoticeVariant = 'section' | 'compact' | 'mutation' | 'stale'

interface ErrorNoticeProps {
  title: string
  error: unknown | null
  variant?: ErrorNoticeVariant
  updatedAt?: number | null
  evidence?: ErrorEvidence[]
  onRetry?: () => void | Promise<void>
}

/** 常挂错误槽：出现/收起只走 grid-fr 布局流，不额外叠加淡入或位移动效。 */
export function ErrorNotice({
  title,
  error,
  variant = 'section',
  updatedAt = null,
  evidence = [],
  onRetry,
}: ErrorNoticeProps) {
  const open = error != null
  const current = useMemo(() => open ? errorInfo(error) : null, [error, open])
  const [retained, setRetained] = useState<ErrorInfo | null>(current)
  const [expanded, setExpanded] = useState(false)
  const evidenceId = useId()

  useEffect(() => {
    if (current) setRetained(current)
    else setExpanded(false)
  }, [current, open])

  const shown = current ?? retained
  const allEvidence = [...(shown?.evidence ?? []), ...evidence]
  const compact = variant === 'compact' || variant === 'stale'
  const blocked = variant === 'mutation'
  const label = variant === 'stale' && updatedAt != null
    ? `${title}，当前显示 ${timeAgo(updatedAt)}的数据`
    : title

  return (
    <div className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
      <div className="min-h-0 overflow-hidden" inert={!open}>
        <div
          className={`${compact ? 'py-1.5 text-[12.5px]' : 'my-2 py-2 text-[13px]'} ${blocked ? 'rounded-[6px] bg-warn-soft px-2.5' : 'border-l-2 border-warn pl-2.5'}`}
          role={variant === 'mutation' ? 'alert' : 'status'}
          aria-live={variant === 'mutation' ? 'assertive' : 'polite'}
        >
          <div className="flex min-w-0 items-start gap-2">
            <TriangleAlert size={compact ? 14 : 16} className="mt-0.5 flex-none text-warn" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="font-medium text-warn">{label}</div>
              {shown && <div className="mt-0.5 text-ink-2"><InkRewrite text={shown.message} tone="label" /></div>}
            </div>
            {onRetry && (
              <Tooltip content="重试">
                <button
                  type="button"
                  aria-label={`重试：${title}`}
                  className="flex-none cursor-pointer text-ink-3 hover:text-warn"
                  onClick={() => void onRetry()}
                >
                  <RefreshCw size={15} aria-hidden />
                </button>
              </Tooltip>
            )}
          </div>
          {allEvidence.length > 0 && (
            <>
              <button
                type="button"
                className="mt-1 cursor-pointer text-[11.5px] text-ink-3 hover:text-ink-2"
                aria-expanded={expanded}
                aria-controls={evidenceId}
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? '收起证据' : '查看证据'}
              </button>
              <div className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                <div id={evidenceId} className="min-h-0 overflow-hidden" inert={!expanded}>
                  <dl className="mt-1.5 space-y-1 border-t border-line pt-1.5 text-[11.5px] text-ink-3">
                    {allEvidence.map((item) => (
                      <div key={`${item.label}:${item.value}`} className="flex gap-2">
                        <dt className="flex-none">{item.label}</dt>
                        <dd className="num min-w-0 break-all">{item.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
