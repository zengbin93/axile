import { useCallback } from 'react'
import { useParams } from 'react-router'
import { Card } from '@/components/ui/Card'
import { Skeleton, SkeletonLines } from '@/components/ui/Skeleton'
import { ErrorNotice } from '@/components/ui/ErrorNotice'
import { HoldingsView } from '@/features/account/HoldingsView'
import { AccountPageTitle } from '@/features/account/pageHead'
import { accountAssetTerms } from '@/features/dashboard/display'
import { TargetSnapshotControl } from '@/features/portfolio/TargetSnapshotControl'
import { getAccount, getAccountAssetSnapshots, getAccountTargetSnapshot, refreshAccountTargetSnapshot } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { useTargetSnapshot } from '@/lib/hooks/useTargetSnapshot'
import { currencyOf, positionsOfAssets } from '@/lib/derive'
import { useDomainStore } from '@/stores/domain'
import { useRunning } from '@/stores/liveExec'

/**
 * 持仓明细路由页 /accounts/:id/holdings。
 *
 * 由抽屉升级而来：换回可深链/刷新/后退的 URL。账户名/权益读自共享 store，
 * 持仓取自最近一次账户资产观测、目标取自组合最新权重，逐只对照复用 HoldingsView。
 */
export function AccountHoldingsPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const accounts = useDomainStore((s) => s.accounts)
  const item = accounts?.find((a) => a.account_id === accountId) ?? null
  const assetTerms = accountAssetTerms(item?.trade_channel)
  const running = useRunning(accountId)

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), {
    queryKey: `account:${accountId}`,
    intervalMs: 15000,
  })
  const snapshots = usePolling(
    useCallback((s: AbortSignal) => getAccountAssetSnapshots(accountId, { limit: 1 }, s), [accountId]),
    { queryKey: `account:${accountId}:asset-snapshots:1`, intervalMs: 10000 },
  )
  // 目标改取账户级「执行器口径」权重（后端已叠加杠杆与精度），与含杠杆的真实持仓同尺。
  const weights = useTargetSnapshot(
    useCallback((s: AbortSignal) => getAccountTargetSnapshot(accountId, s), [accountId]),
    useCallback(() => refreshAccountTargetSnapshot(accountId), [accountId]),
    `account:${accountId}:target-snapshot`,
  )

  const latestAssets = snapshots.data?.data[0]?.assets
  const positions = positionsOfAssets(latestAssets)
  const target = weights.data?.weights ?? {}
  const recEquity = Number(latestAssets?.total_asset) || 0
  const equity = item?.total_asset ?? recEquity
  const tradeChannel = item?.trade_channel ?? account.data?.trade_channel
  const portfolioId = item?.portfolio_id ?? account.data?.portfolio_id ?? null
  // 快照缺失但实时口径（dashboard.holdings_count）显示有持仓：资产观测未返回有效持仓明细，
  // 逐只对照会把「实际持有」误判为空仓并给出「买入建仓」的危险建议。此时降级为「待刷新」，
  // 不展示可能翻倍的调仓计划（对齐 derive.ts 头部「不能确定的不编」原则）。
  const holdingsCount = item?.holdings_count ?? 0
  const holdingsStale = positions.length === 0 && holdingsCount > 0

  return (
    <section>
      <div className="flex flex-wrap items-baseline gap-3">
        <AccountPageTitle
          accountId={accountId}
          page="持仓明细"
          name={item?.name ?? account.data?.name}
          channel={tradeChannel}
          market={item?.market ?? account.data?.market}
        />
      </div>

      <Card className="mt-4 px-6 py-5">
        <div className="mb-3 border-b border-line pb-3">
          <TargetSnapshotControl
            snapshot={weights.data}
            loading={weights.loading}
            recalculating={weights.recalculating}
            error={weights.recalculateError}
            disabled={!!running || portfolioId == null}
            disabledReason={running ? '账户正在执行，结束后可重新计算' : portfolioId == null ? '账户未绑定组合' : undefined}
            onRecalculate={() => void weights.recalculate()}
          />
        </div>
        {(!snapshots.data || !weights.data) && (snapshots.loading || weights.loading) ? (
          <div aria-label="正在加载持仓与目标" aria-busy="true">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-4 w-20" />
            </div>
            <SkeletonLines rows={6} className="mt-3" />
          </div>
        ) : snapshots.error || weights.error ? null : !weights.data?.calculated_at ? (
          <div className="text-[14px] text-ink-3">尚无目标权重，点击刷新按钮计算后再查看持仓对照。</div>
        ) : holdingsStale ? (
          <div className="text-[14px] leading-relaxed text-warn">
            持仓数据待刷新 —— 实时口径显示当前持有 {holdingsCount} 个品种，但最近的资产观测未返回持仓明细。
            <span className="mt-1 block text-ink-3">
              为避免给出「买入建仓」等错误调仓建议，这里暂不展示逐只对照；刷新账户权益后即可恢复。
            </span>
          </div>
        ) : (
          <HoldingsView
            positions={positions}
            target={target}
            equity={equity}
            currency={currencyOf(item?.currency)}
            assetLabel={assetTerms.shortLabel}
            quantities={weights.data?.quantities ?? null}
          />
        )}
        <ErrorNotice
          title="持仓对照加载失败"
          error={snapshots.error ?? weights.error}
          variant={snapshots.stale || weights.data != null ? 'stale' : 'section'}
          updatedAt={snapshots.updatedAt ?? weights.updatedAt}
          onRetry={() => Promise.all([snapshots.refresh(), weights.reloadSnapshot()]).then(() => undefined)}
        />
      </Card>
    </section>
  )
}
