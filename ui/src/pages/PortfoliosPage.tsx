import { useCallback, useState } from 'react'
import { useViewTransitionState } from 'react-router'
import { Pencil, Trash2 } from 'lucide-react'
import { Link, useNavigate } from '@/components/ui/nav'
import { Card, Chip } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { Tooltip } from '@/components/ui/Tooltip'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { deletePortfolio, getPortfolioTargetSnapshot } from '@/lib/api/portfolios'
import {
  formatTargetWeight,
  formatTargetUpdatedAt,
  portfolioTargetState,
  type PortfolioTargetState,
} from '@/features/portfolio/portfolioCardSummary'
import { channelLabel } from '@/features/dashboard/display'
import { usePolling } from '@/lib/hooks/usePolling'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import type { AccountDashboardItem, PortfolioLite } from '@/types/api'

/** 组合列表 /portfolios —— 组合的「家」，保证每个组合始终可达 + 管理入口。 */
export function PortfoliosPage() {
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)
  const [deleteError, setDeleteError] = useState<Error | null>(null)

  const portfolios = useDomainStore((s) => s.portfolios)
  const accounts = useDomainStore((s) => s.accounts)
  const portfoliosError = useDomainStore((s) => s.portfoliosError)
  const accountsError = useDomainStore((s) => s.accountsError)
  const refreshPortfolios = useDomainStore((s) => s.refreshPortfolios)

  const followersOf = (pid: number | null): AccountDashboardItem[] =>
    pid == null ? [] : (accounts ?? []).filter((a) => a.portfolio_id === pid)

  const askDelete = (p: PortfolioLite) => {
    if (p.id == null) return
    const followers = followersOf(p.id)
    if (followers.length > 0) {
      const names = followers.map((f) => f.name).join('、')
      setConfirm({
        title: '无法删除',
        body: `「${p.name}」正被账户 ${names} 绑定。需先在该账户改绑到其它组合、或解绑后，才能删除本组合。`,
        okText: `查看 ${followers[0].name}`,
        onConfirm: () => navigate(`/accounts/${followers[0].account_id}`),
      })
      return
    }
    setConfirm({
      title: '删除组合',
      body: `删除「${p.name}」。此操作不可撤销。`,
      okText: '删除',
      danger: true,
      onConfirm: async () => {
        setDeleteError(null)
        try {
          await deletePortfolio(p.id!)
          toast('组合已删除')
          void refreshPortfolios()
        } catch (e) {
          setDeleteError(e instanceof Error ? e : new Error(String(e)))
        }
      },
    })
  }

  const list = portfolios ?? []

  return (
    <section>
      {portfolios == null && !portfoliosError && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,380px),1fr))] gap-3">
          {Array.from({ length: 4 }, (_, index) => (
            <Card key={index} className="min-h-[260px] px-5 py-5" aria-busy="true">
              <div className="flex justify-between gap-4"><Skeleton className="h-5 w-32" /><Skeleton className="h-8 w-20" /></div>
              <Skeleton className="mt-3 h-5 w-36" />
              <div className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-4">
                {Array.from({ length: 3 }, (_, metric) => <Skeleton key={metric} className="h-9 w-full" />)}
              </div>
              <Skeleton className="mt-4 h-12 w-full" />
              <Skeleton className="mt-4 h-8 w-2/3" />
            </Card>
          ))}
        </div>
      )}
      <ErrorNotice
        title={portfolios == null ? '组合加载失败' : '组合更新失败'}
        error={portfoliosError}
        variant={portfolios == null ? 'section' : 'stale'}
        onRetry={refreshPortfolios}
      />
      <ErrorNotice title="删除组合失败" error={deleteError} variant="mutation" />

      {portfolios != null && list.length === 0 && (
        <Card className="p-8 text-center">
          <p className="text-[15px] font-[620]">还没有组合</p>
          <p className="mt-2 text-[14px] text-ink-2">组合是「交易什么」的来源，可被多个账户复用。</p>
          <Link to="/setup/pf/name" className="mt-4 inline-block text-[14px] font-semibold text-accent">
            新建组合 →
          </Link>
        </Card>
      )}

      {list.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,380px),1fr))] gap-3">
          {list.map((p) => (
            <PortfolioCard key={p.id} p={p} followers={followersOf(p.id)} accountsReady={accounts != null} accountsError={accountsError} onDelete={askDelete} />
          ))}
        </div>
      )}

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

/** 组合列表卡。抽成组件以便每卡独立用 useViewTransitionState 挂共享名（共享元素 FLIP）。 */
function PortfolioCard({
  p,
  followers,
  accountsReady,
  accountsError,
  onDelete,
}: {
  p: PortfolioLite
  followers: AccountDashboardItem[]
  accountsReady: boolean
  accountsError: Error | null
  onDelete: (p: PortfolioLite) => void
}) {
  const navigate = useNavigate()
  const to = `/portfolios/${p.id}`
  const target = usePolling(
    useCallback(
      (signal: AbortSignal) => getPortfolioTargetSnapshot(p.id!, signal),
      [p.id],
    ),
    { queryKey: `portfolio:${p.id}:target-snapshot`, intervalMs: 0, enabled: p.id != null },
  )
  const targetState = portfolioTargetState(target.data, target.loading, target.error, target.stale)
  // 仅「正在跳去本组合详情」时给组合名挂共享名，与详情头配对做平移放大。
  const nameVt = useViewTransitionState(to)
  return (
    <Card
      className="flex min-h-[260px] min-w-0 flex-col px-5 py-5 transition-transform hover:-translate-y-px"
      onClick={() => navigate(to)}
    >
      <div className="flex min-w-0 items-start justify-between gap-4">
        <div className="min-w-0">
          <div
            className="truncate text-[16px] font-[640]"
            style={nameVt && p.id != null ? { viewTransitionName: `portfolio-name-${p.id}` } : undefined}
          >
            {p.name}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Chip>{p.market}</Chip>
            <Chip>自定义函数</Chip>
          </div>
        </div>
        <div className="flex flex-none items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <Tooltip content="编辑组合">
            <button
              type="button"
              aria-label="编辑组合"
              className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg border border-line text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
              onClick={() => navigate(to + '/edit')}
            >
              <Pencil size={14} aria-hidden />
            </button>
          </Tooltip>
          <Tooltip content={accountsReady && !accountsError ? '删除组合' : '绑定关系确认后才能删除'}>
            <button
              type="button"
              aria-label="删除组合"
              className="grid h-8 w-8 cursor-pointer place-items-center rounded-lg border border-warn/35 bg-warn-tint text-warn hover:border-warn/55 hover:bg-warn-soft disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!accountsReady || Boolean(accountsError)}
              onClick={() => onDelete(p)}
            >
              <Trash2 size={14} aria-hidden />
            </button>
          </Tooltip>
        </div>
      </div>

      <TargetSummary state={targetState} />

      <div className="mt-auto flex min-w-0 flex-wrap items-end justify-between gap-3 border-t border-line pt-3.5 text-[12.5px] text-ink-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          {accountsError ? (
            <span className="text-warn">绑定关系暂不可用</span>
          ) : !accountsReady ? (
            <Skeleton className="h-7 w-36" />
          ) : followers.length > 0 ? (
            followers.map((follower) => <PortfolioFollowerLink key={follower.account_id} account={follower} />)
          ) : (
            '未绑定账户'
          )}
        </div>
        <TargetTimestamp state={targetState} />
      </div>
    </Card>
  )
}

function TargetSummary({ state }: { state: PortfolioTargetState }) {
  if (state.kind === 'loading') {
    return (
      <div className="mt-4 grid grid-cols-3 gap-5 border-t border-line pt-3.5" aria-busy="true" aria-label="正在读取组合目标">
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index}><Skeleton className="h-3 w-14" /><Skeleton className="mt-2 h-4 w-20" /></div>
        ))}
        <Skeleton className="col-span-3 h-3 w-2/3 max-w-[460px]" />
      </div>
    )
  }

  if (state.kind === 'unavailable' || state.kind === 'uncalculated' || state.kind === 'empty') {
    const text = state.kind === 'unavailable'
      ? '目标暂不可用'
      : state.kind === 'uncalculated'
        ? '尚无目标快照'
        : '目标为空仓'
    return (
      <div className="mt-4 flex min-h-[62px] items-center border-t border-line pt-3.5">
        <span className={`text-[13px] ${state.kind === 'unavailable' ? 'text-warn' : 'text-ink-3'}`}>{text}</span>
      </div>
    )
  }

  const { summary } = state
  return (
    <div className="mt-4 border-t border-line pt-3.5">
      <div className="grid grid-cols-3 gap-3">
        <Metric label="目标品种" value={`${summary.activeCount} 个`} />
        <Metric label="总敞口" value={formatTargetWeight(summary.grossExposure, false)} />
        <Metric label="净敞口" value={formatTargetWeight(summary.netExposure)} />
      </div>
      <div className="mt-3 grid min-h-[42px] grid-cols-2 gap-x-4 gap-y-1.5 text-[12.5px] text-ink-2">
        {summary.topEntries.map((entry) => (
          <div key={entry.symbol} className="flex min-w-0 items-center justify-between gap-2">
            <span className="truncate" title={entry.symbol}>{entry.symbol}</span>
            <span className="flex-none text-ink-3">{formatTargetWeight(entry.weight)}</span>
          </div>
        ))}
      </div>
      {summary.hiddenCount > 0 && <div className="mt-1.5 text-[11.5px] text-ink-3">另有 {summary.hiddenCount} 个目标品种</div>}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11.5px] text-ink-3">{label}</div>
      <div className="mt-0.5 truncate text-[14px] font-[620] text-ink-1">{value}</div>
    </div>
  )
}

function TargetTimestamp({ state }: { state: PortfolioTargetState }) {
  if (state.kind !== 'ready' && state.kind !== 'empty') return null
  return (
    <span className={`flex-none text-[11.5px] ${state.stale ? 'text-warn' : ''}`}>
      目标更新于{formatTargetUpdatedAt(state.calculatedAt)}{state.stale ? ' · 更新失败' : ''}
    </span>
  )
}

function PortfolioFollowerLink({ account }: { account: AccountDashboardItem }) {
  const to = `/accounts/${account.account_id}`
  const transitioning = useViewTransitionState(to)
  return (
    <Link
      to={to}
      className="-m-1 inline-flex min-w-0 items-center gap-2 rounded-md p-1 text-inherit hover:bg-fill focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      onClick={(event) => event.stopPropagation()}
      aria-label={`查看账户 ${account.name}，${channelLabel(account.trade_channel, account.market)}`}
    >
      <span
        className="max-w-32 truncate text-[14px] font-[620] text-ink-1"
        style={transitioning ? { viewTransitionName: `account-name-${account.account_id}` } : undefined}
      >
        {account.name}
      </span>
      <Chip style={transitioning ? { viewTransitionName: `account-channel-${account.account_id}` } : undefined}>
        {channelLabel(account.trade_channel, account.market)}
      </Chip>
    </Link>
  )
}
