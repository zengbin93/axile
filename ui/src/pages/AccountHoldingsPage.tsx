import { useCallback } from 'react'
import { useParams } from 'react-router'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card } from '@/components/ui/Card'
import { SkeletonLines } from '@/components/ui/Skeleton'
import { HoldingsView } from '@/features/account/HoldingsView'
import { getAccount, getAccountTargetWeights, getExecuteRecords } from '@/lib/api/accounts'
import { usePolling } from '@/lib/hooks/usePolling'
import { currencyOf, positionsOf } from '@/lib/derive'
import { useDomainStore } from '@/stores/domain'
import type { LatestWeights } from '@/types/api'

/**
 * 持仓明细路由页 /accounts/:id/holdings。
 *
 * 由抽屉升级而来：换回可深链/刷新/后退的 URL。账户名/权益读自共享 store，
 * 持仓取自最近一条执行记录、目标取自组合最新权重，逐只对照复用 HoldingsView。
 */
export function AccountHoldingsPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const accounts = useDomainStore((s) => s.accounts)
  const item = accounts?.find((a) => a.account_id === accountId) ?? null

  const account = usePolling(useCallback((s: AbortSignal) => getAccount(accountId, s), [accountId]), 15000)
  const records = usePolling(
    useCallback((s: AbortSignal) => getExecuteRecords(accountId, { limit: 50 }, s), [accountId]),
    10000,
  )
  // 目标改取账户级「执行器口径」权重（后端已叠加杠杆与精度），与含杠杆的真实持仓同尺。
  const weights = usePolling<LatestWeights>(
    useCallback((s: AbortSignal) => getAccountTargetWeights(accountId, s), [accountId]),
    60000,
    accountId,
  )

  const positions = positionsOf(records.data?.data ?? [])
  const target = weights.data ?? {}
  const recEquity = Number(records.data?.data?.[0]?.raw_result?.account_assets?.total_asset) || 0
  const equity = item?.total_asset ?? recEquity
  const name = item?.name ?? account.data?.name ?? `账户 #${accountId}`
  // 快照缺失但实时口径（dashboard.holdings_count）显示有持仓：执行记录未产出账户快照，
  // 逐只对照会把「实际持有」误判为空仓并给出「买入建仓」的危险建议。此时降级为「待刷新」，
  // 不展示可能翻倍的调仓计划（对齐 derive.ts 头部「不能确定的不编」原则）。
  const holdingsCount = item?.holdings_count ?? 0
  const holdingsStale = positions.length === 0 && holdingsCount > 0

  return (
    <section>
      <Breadcrumb
        trail={[
          { label: name, to: `/accounts/${accountId}` },
          { label: '持仓明细' },
        ]}
      />
      <div className="mt-3 text-[18px] font-[640]">{name}</div>

      <Card className="mt-4 max-w-[760px] px-6 py-5">
        {records.loading ? (
          <SkeletonLines rows={6} />
        ) : records.error ? (
          <p className="text-[14px] text-bad">加载失败：{records.error.message}</p>
        ) : holdingsStale ? (
          <div className="text-[14px] leading-relaxed text-warn">
            持仓数据待刷新 —— 实时口径显示当前持有 {holdingsCount} 个品种，但最近的执行记录未产出账户快照。
            <span className="mt-1 block text-ink-3">
              为避免给出「买入建仓」等错误调仓建议，这里暂不展示逐只对照；下次成功执行后即恢复。
            </span>
          </div>
        ) : (
          <HoldingsView
            positions={positions}
            target={target}
            equity={equity}
            currency={currencyOf(item?.currency)}
          />
        )}
      </Card>
    </section>
  )
}
