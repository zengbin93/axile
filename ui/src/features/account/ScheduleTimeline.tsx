import {
  formatBeijingTimestamp,
  formatPlannedAt,
  formatRecentExecution,
  formatTimeUntil,
} from '@/lib/scheduleTime'
import { ScheduleTimeRow } from '@/components/ui/ScheduleTimeRow'
import { Skeleton, SkeletonGroup } from '@/components/ui/Skeleton'

interface ScheduleTimelineProps {
  lastExecutedAt: string | null
  nextRunTimes: string[]
  /** 测试可注入固定时钟；生产默认使用当前时间。 */
  now?: number
}

interface ScheduleSummaryProps {
  lastExecutedAt: string | null
  nextRunAt: string | null
  /** 测试可注入固定时钟；生产默认使用当前时间。 */
  now?: number
}

/** 账户头部的最近执行与下次计划摘要。 */
export function ScheduleSummary({ lastExecutedAt, nextRunAt, now = Date.now() }: ScheduleSummaryProps) {
  return (
    <div className="mt-1.5 text-[13px] text-ink-3">
      {lastExecutedAt ? (
        <time dateTime={lastExecutedAt} title={formatBeijingTimestamp(lastExecutedAt)}>
          上次 {formatRecentExecution(lastExecutedAt, now)}
        </time>
      ) : (
        '尚无执行'
      )}
      {nextRunAt && (
        <>
          {' · '}
          <time dateTime={nextRunAt} title={formatBeijingTimestamp(nextRunAt)}>
            下次 {formatPlannedAt(nextRunAt, now)}
          </time>
        </>
      )}
    </div>
  )
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
              <ScheduleTimeRow
                key={iso}
                scheduledAt={iso}
                trailing={formatTimeUntil(iso, now)}
                now={now}
                tone="muted"
                size="md"
                className="[&>span]:text-[12px]"
              />
            ))}
          </div>
        ) : (
          <div className="font-medium text-ink-1">暂无自动执行计划</div>
        )}
      </div>
    </div>
  )
}

/** 与真实时间线同高的首次加载占位。 */
export function ScheduleTimelineSkeleton() {
  return (
    <SkeletonGroup label="正在加载自动执行计划" className="border-t border-line">
      <div className="flex items-center justify-between gap-3 py-1.5">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-12" />
      </div>
      <div className="space-y-2 border-t border-line py-1.5">
        <Skeleton className="h-4 w-12" />
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="flex items-center justify-between gap-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-14" />
          </div>
        ))}
      </div>
    </SkeletonGroup>
  )
}
