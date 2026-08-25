import { useCallback, useState, type ReactNode } from 'react'
import { useParams, useViewTransitionState } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { Card, SectionLabel, Chip } from '@/components/ui/Card'
import { Skeleton, SkeletonLines } from '@/components/ui/Skeleton'
import { ExposureBar } from '@/components/viz/ExposureBar'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { OverflowText } from '@/components/ui/OverflowText'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { getPortfolio, getPortfolioTargetSnapshot, refreshPortfolioTargetSnapshot } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { triggerExecute } from '@/lib/api/executions'
import { usePolling } from '@/lib/hooks/usePolling'
import { useTargetSnapshot } from '@/lib/hooks/useTargetSnapshot'
import { useToastStore } from '@/stores/ui'
import { channelLabel } from '@/features/dashboard/display'
import { TargetSnapshotControl } from '@/features/portfolio/TargetSnapshotControl'
import { useLiveExecStore } from '@/stores/liveExec'

export function PortfolioDetailPage() {
  const { id } = useParams()
  const portfolioId = Number(id)
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)
  const [actionError, setActionError] = useState<Error | null>(null)

  const portfolio = usePolling(useCallback((s: AbortSignal) => getPortfolio(portfolioId, s), [portfolioId]), {
    queryKey: `portfolio:${portfolioId}`,
    intervalMs: 0,
  })
  const accounts = useDomainStore((s) => s.accounts)
  const accountsError = useDomainStore((s) => s.accountsError)
  const portfolios = useDomainStore((s) => s.portfolios)

  const pf = portfolio.data
  // 组合列表已在共享 store 里，冷拉详情时先用它渲染页头，避免整屏塌成一行（L1 消闪）。
  const lite = portfolios?.find((p) => p.id === portfolioId) ?? null
  const head = pf ?? lite
  const boundAccount = accounts?.find((a) => a.portfolio_id === portfolioId) ?? null
  const boundAccountRun = useLiveExecStore((state) =>
    accounts?.some((account) => account.portfolio_id === portfolioId && state.running.has(account.account_id)) ?? false,
  )

  // 共享元素 FLIP：组合名与列表卡配对（A）；绑定账户名与账户详情头配对（B，复用 account-name）。
  const pfNameVt = useViewTransitionState(`/portfolios/${portfolioId}`)
  const acctNameVt = useViewTransitionState(boundAccount ? `/accounts/${boundAccount.account_id}` : '__none__')

  const weights = useTargetSnapshot(
    useCallback((s: AbortSignal) => getPortfolioTargetSnapshot(portfolioId, s), [portfolioId]),
    useCallback(() => refreshPortfolioTargetSnapshot(portfolioId), [portfolioId]),
    `portfolio:${portfolioId}:target-snapshot`,
    pf !== null,
  )

  if (portfolio.error && !pf)
    return (
      <section>
        <ErrorNotice title="组合加载失败" error={portfolio.error} onRetry={portfolio.refresh} />
      </section>
    )

  const target = weights.data?.weights ?? {}
  const targetRows = Object.entries(target)
    .filter(([, w]) => Math.abs(w) > 1e-9)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const coverage = targetRows.reduce((s, [, w]) => s + Math.abs(w), 0) * 100

  const runFanout = () => {
    if (!boundAccount) return
    setConfirm({
      title: '全部跟随账户立即执行',
      body: `通知跟随本组合的账户（${boundAccount.name}）立即按最新目标调仓。若目标未变，多数会空跑、几乎不增成本。`,
      okText: '通知执行',
      onConfirm: async () => {
        setActionError(null)
        try {
          await triggerExecute(boundAccount.account_id)
          toast(`已通知 ${boundAccount.name} 立即调仓`)
        } catch (e) {
          setActionError(e instanceof Error ? e : new Error(String(e)))
        }
      },
    })
  }

  return (
    <section>
      {/* Hero：有 head（成品或列表 lite）即时渲染，全空才骨架 */}
      <Card className="p-6">
        {head ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span
                className="text-[18px] font-[640]"
                style={pfNameVt ? { viewTransitionName: `portfolio-name-${portfolioId}` } : undefined}
              >
                {head.name}
              </span>
              <Chip>{head.market}</Chip>
              <Chip>自定义函数</Chip>
            </div>
            {head.description && <div className="mt-2 text-[13px] text-ink-2">{head.description}</div>}
            <div className="mt-6 flex gap-8 border-t border-line pt-4">
              <Meta k="跟随账户" v={accountsError ? <span className="text-warn">暂不可用</span> : accounts == null ? <Skeleton className="h-5 w-16" /> : boundAccount ? '1 个' : '未绑定'} />
              <Meta k="目标覆盖" v={!weights.data && weights.loading ? <Skeleton className="h-5 w-16" /> : weights.error ? <span className="text-warn">暂不可用</span> : targetRows.length ? `${coverage.toFixed(0)}%` : '—'} />
              <Meta k="创建" v={head.created_at.slice(0, 10)} />
            </div>
            <div className="mt-6 flex gap-2.5">
              <button
                className="cursor-pointer rounded-[9px] border border-line bg-surface px-4 py-2 text-[13.5px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
                onClick={() => navigate(`/portfolios/${portfolioId}/edit`)}
              >
                编辑组合
              </button>
              {accounts != null && !accountsError && boundAccount && (
                <button
                  className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-4 py-2 text-[13.5px] font-[550] text-surface"
                  onClick={runFanout}
                >
                  全部跟随账户立即执行
                </button>
              )}
            </div>
            <ErrorNotice title="触发执行失败" error={actionError} variant="mutation" onRetry={runFanout} />
          </>
        ) : (
          <>
            <Skeleton className="h-6 w-52" />
            <Skeleton className="mt-3 h-4 w-full" />
            <Skeleton className="mt-6 h-10 w-64" />
          </>
        )}
      </Card>

      {/* 原始目标 */}
      <SectionLabel>组合原始目标 · 各账户再套自己的风控/杠杆</SectionLabel>
      <Card className="px-6 py-4">
        {pf && (
          <div className="mb-3 border-b border-line pb-3">
            <TargetSnapshotControl
              snapshot={weights.data}
              loading={weights.loading}
              recalculating={weights.recalculating}
              error={weights.recalculateError}
              disabled={!!boundAccountRun}
              disabledReason={boundAccountRun ? '账户正在执行，结束后可重新计算' : undefined}
              contextName={accounts?.find((a) => a.account_id === weights.data?.context_account_id)?.name
                ?? (weights.data?.context_account_id != null ? `#${weights.data.context_account_id}` : null)}
              onRecalculate={() => void weights.recalculate()}
            />
          </div>
        )}
        {!pf && <SkeletonLines rows={3} />}
        {pf && !weights.data && weights.loading && <SkeletonLines rows={3} />}
        <ErrorNotice
          title="目标权重快照加载失败"
          error={pf ? weights.error : null}
          variant={weights.stale ? 'stale' : 'section'}
          updatedAt={weights.updatedAt}
          onRetry={weights.reloadSnapshot}
        />
        {pf && !weights.loading && !weights.error && !weights.data?.calculated_at && (
          <p className="text-[13px] text-ink-3">尚无目标权重，点击刷新按钮计算。</p>
        )}
        {pf && !weights.loading && !weights.error && weights.data?.calculated_at && targetRows.length === 0 && (
          <p className="text-[13px] text-ink-3">当前目标为空仓。</p>
        )}
        {targetRows.length > 0 && (
          <>
            <div className="mb-1 text-[13px] text-ink-2">
              {targetRows.length} 只 · 最大 {targetRows[0][0]} {(targetRows[0][1] * 100).toFixed(1)}%
            </div>
            <ExposureBar weights={targetRows.map(([, w]) => w)} />
            <div className="mt-2">
              {targetRows.map(([sym, w]) => (
                <div key={sym} className="flex items-center gap-3 border-t border-line py-2.5 text-[13.5px] first:border-t-0">
                  <OverflowText className="min-w-0 flex-1" text={sym} />
                  <span className={`num w-16 flex-none text-right font-semibold ${w < 0 ? 'text-bad' : ''}`}>
                    {(w * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      {/* 跟随账户 */}
      <SectionLabel>跟随此组合的账户</SectionLabel>
      <Card className="px-6 py-2">
        {accounts == null && !accountsError ? (
          <div className="py-3"><Skeleton className="h-4 w-36" /><Skeleton className="mt-2 h-3 w-24" /></div>
        ) : accountsError ? (
          <ErrorNotice title="绑定关系加载失败" error={accountsError} onRetry={() => useDomainStore.getState().refreshAccounts()} />
        ) : boundAccount ? (
          <Link
            to={`/accounts/${boundAccount.account_id}`}
            className="flex items-center gap-3 py-3 text-inherit hover:bg-bg-subtle"
          >
            <div>
              <div
                className="text-[14px] font-semibold"
                style={acctNameVt ? { viewTransitionName: `account-name-${boundAccount.account_id}` } : undefined}
              >
                {boundAccount.name}
              </div>
              <div className="text-xs text-ink-3">{channelLabel(boundAccount.trade_channel, boundAccount.market)}</div>
            </div>
            <span className="ml-auto text-[18px] text-ink-3">›</span>
          </Link>
        ) : (
          <p className="py-3 text-[13px] text-ink-3">暂无账户跟随此组合。</p>
        )}
      </Card>

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

function Meta({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-ink-3">{k}</div>
      <div className="mt-px text-[16px] font-semibold">{v}</div>
    </div>
  )
}
