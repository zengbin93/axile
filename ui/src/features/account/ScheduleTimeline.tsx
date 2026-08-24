import {
  formatBeijingTimestamp,
  formatPlannedAt,
  formatRecentExecution,
  formatTimeUntil,
} from '@/features/account/scheduleTime'

interface ScheduleTimelineProps {
  lastExecutedAt: string | null
  nextRunTimes: string[]
  /** 测试可注入固定时钟；生产默认使用当前时间。 */
  now?: number
}

/** 自动执行卡片中的最近执行与未来三次时间表。 */
export function ScheduleTimeline({ lastExecutedAt, nextRunTimes, now = Date.now() }: ScheduleTimelineProps) {
  const upcoming = nextRunTimes.slice(0, 3)
  return (
    <div className="border-t border-line">
      <div className="flex items-center justify-between gap-3 py-1.5 text-[14px]">
        <span className="text-ink-2">最近一次执行</span>
        {lastExecutedAt ? (
          <time
            dateTime={lastExecutedAt}
            title={formatBeijingTimestamp(lastExecutedAt)}
            className="font-medium text-ink-1"
          >
            {formatRecentExecution(lastExecutedAt, now)}
          </time>
        ) : (
          <span className="font-medium text-ink-1">尚无执行</span>
        )}
      </div>

      <div className="border-t border-line py-1.5 text-[14px]">
        <div className="mb-1 text-ink-2">接下来</div>
        {upcoming.length > 0 ? (
          <div role="list" aria-label="未来自动执行计划" className="space-y-1">
            {upcoming.map((iso) => (
              <div role="listitem" key={iso} className="flex items-baseline justify-between gap-3">
                <time dateTime={iso} title={formatBeijingTimestamp(iso)} className="num font-medium text-ink-1">
                  {formatPlannedAt(iso, now)}
                </time>
                <span className="flex-none text-[12px] text-ink-3">{formatTimeUntil(iso, now)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="font-medium text-ink-1">暂无自动执行计划</div>
        )}
      </div>
    </div>
  )
}
