import { timeAgo } from '@/lib/format'

/** 贴近数据的轻量新鲜度状态；根因与重试统一由全局连接状态承载。 */
export function StaleDataStatus({
  updatedAt,
  now,
  label = '数据',
}: {
  updatedAt: number | null
  now?: number
  label?: string
}) {
  if (updatedAt == null) return null
  return (
    <span role="status" className="flex-none whitespace-nowrap text-[11.5px] font-medium text-warn">
      {label}停留在 {timeAgo(updatedAt, now)}
    </span>
  )
}
