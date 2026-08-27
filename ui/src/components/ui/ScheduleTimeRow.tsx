import type { CSSProperties, ReactNode } from 'react'

import { formatBeijingTimestamp, formatPlannedAt } from '@/lib/scheduleTime'

export type ScheduleTimeRowTone = 'default' | 'muted' | 'warning'
export type ScheduleTimeRowSize = 'sm' | 'md'

export interface ScheduleTimeRowProps {
  scheduledAt: string
  trailing: ReactNode
  now?: number
  tone?: ScheduleTimeRowTone
  size?: ScheduleTimeRowSize
  className?: string
  style?: CSSProperties
}

const TONE_CLASS: Record<ScheduleTimeRowTone, string> = {
  default: 'text-ink-2',
  muted: 'text-ink-3',
  warning: 'text-warn',
}

const SIZE_CLASS: Record<ScheduleTimeRowSize, string> = {
  sm: 'text-[14px]',
  md: 'text-[15px]',
}

/** 通用排程行：自然时间在左，场景化状态或相对时间在右。 */
export function ScheduleTimeRow({
  scheduledAt,
  trailing,
  now = Date.now(),
  tone = 'default',
  size = 'sm',
  className = '',
  style,
}: ScheduleTimeRowProps) {
  const exactTime = formatBeijingTimestamp(scheduledAt)
  return (
    <div
      role="listitem"
      className={`grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-baseline gap-3 ${SIZE_CLASS[size]} ${className}`}
      style={style}
    >
      <time
        dateTime={scheduledAt}
        title={exactTime}
        className="num min-w-0 truncate font-medium text-ink-1"
      >
        {formatPlannedAt(scheduledAt, now)}
      </time>
      <span title={typeof trailing === 'string' ? trailing : undefined} className={`min-w-0 truncate text-right ${TONE_CLASS[tone]}`}>
        {trailing}
      </span>
    </div>
  )
}
