import { useCallback } from 'react'
import { useParams } from 'react-router'
import { ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { Skeleton } from '@/components/ui/Skeleton'
import { useNavigate } from '@/components/ui/nav'
import { buildRecentActivity, type RecentRow } from '@/features/account/recent'
import { AccountPageTitle } from '@/features/account/pageHead'
import { getAccountActivity } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'

function statusOf(row: RecentRow): { label: string; className: string; description: string } {
  if (row.type === 'fill') return { label: '已完成', className: 'text-accent', description: `${row.desc} · ${row.amount}` }
  if (row.type === 'fail') return { label: '需处理', className: 'text-warn', description: row.reason || '执行失败' }
  if (row.type === 'terminated') return { label: '已终止', className: 'text-ink-2', description: row.count > 1 ? `${row.count} 次执行已终止` : '执行已终止' }
  if (row.type === 'skip') return { label: '已跳过', className: 'text-ink-2', description: row.count > 1 ? `${row.count} 次因休市跳过` : '排程因休市跳过' }
  return { label: '无变动', className: 'text-ink-2', description: row.count > 1 ? `${row.count} 次目标未变` : '目标未变，无需调仓' }
}

/** 当前账户的完整执行入口；记录可直接下钻到单次执行详情。 */
export function AccountExecutionsPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const navigate = useNavigate()
  const accounts = useDomainStore((state) => state.accounts)
  const item = accounts?.find((account) => account.account_id === accountId) ?? null
  const activity = usePolling(
    useCallback((signal: AbortSignal) => getAccountActivity(accountId, { limit: 100 }, signal), [accountId]),
    { queryKey: `account:${accountId}:activity:100`, intervalMs: 0 },
  )
  const rows = buildRecentActivity(activity.data?.data ?? [], { cap: 100, fetchLimit: 100 }).rows
  return (
    <section>
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-baseline gap-3">
            <AccountPageTitle
              accountId={accountId}
              page="执行记录"
              name={item?.name}
              channel={item?.trade_channel}
              market={item?.market}
            />
          </div>
          <p className="mt-1 text-[13px] text-ink-2">最近的调仓、清仓、终止与排程跳过记录。</p>
        </div>
        {activity.data && <span className="text-[12px] text-ink-3">共 {activity.data.count} 条</span>}
      </div>

      <ErrorNotice title="执行记录加载失败" error={activity.error} variant={activity.data ? 'stale' : 'section'} updatedAt={activity.updatedAt} onRetry={activity.refresh} />

      {!activity.data && activity.loading && (
        <Card className="overflow-hidden" aria-busy="true">
          {Array.from({ length: 7 }, (_, index) => (
            <div key={index} className="grid min-h-[58px] grid-cols-[150px_100px_minmax(0,1fr)_20px] items-center gap-4 border-t border-line px-5 first:border-t-0">
              <Skeleton className="h-3 w-28" /><Skeleton className="h-3 w-16" /><Skeleton className="h-3 w-3/5" /><Skeleton className="h-3 w-3" />
            </div>
          ))}
        </Card>
      )}

      {activity.data && rows.length === 0 && (
        <Card className="px-6 py-12 text-center text-[14px] text-ink-3">暂无执行记录</Card>
      )}

      {rows.length > 0 && (
        <Card className="overflow-hidden">
          <div className="grid grid-cols-[150px_100px_minmax(0,1fr)_20px] gap-4 border-b border-line px-5 py-2.5 text-[11px] font-semibold text-ink-3">
            <span>时间</span><span>结果</span><span>说明</span><span />
          </div>
          {rows.map((row) => {
            const status = statusOf(row)
            const executionId = 'executionId' in row ? row.executionId : null
            return (
              <button
                type="button"
                key={row.key}
                disabled={!executionId}
                onClick={() => executionId && navigate(`/accounts/${accountId}/executions/${executionId}`)}
                className="grid min-h-[58px] w-full grid-cols-[150px_100px_minmax(0,1fr)_20px] items-center gap-4 border-t border-line px-5 text-left text-[13px] first:border-t-0 enabled:hover:bg-bg-subtle disabled:cursor-default"
              >
                <span className="num text-[12px] text-ink-3">{row.time.replace('T', ' ').slice(0, 16)}</span>
                <span className={`font-semibold ${status.className}`}>{status.label}</span>
                <span className="min-w-0 truncate text-ink-2">{status.description}</span>
                {executionId ? <ChevronRight size={15} className="text-ink-3" aria-hidden /> : <span />}
              </button>
            )
          })}
        </Card>
      )}
    </section>
  )
}
