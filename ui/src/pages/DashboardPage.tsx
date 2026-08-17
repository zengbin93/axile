import { useMemo } from 'react'
import { useDomainStore } from '@/stores/domain'
import { FleetView } from '@/features/dashboard/FleetView'
import { AccountDetail } from '@/features/account/AccountDetail'

/** 仪表盘：N=1 原子视图 / N≥2 舰队视图。账户读自共享领域 store。 */
export function DashboardPage() {
  const accounts = useDomainStore((s) => s.accounts)
  const portfolios = useDomainStore((s) => s.portfolios)
  const error = useDomainStore((s) => s.accountsError)
  const refresh = useDomainStore((s) => s.refreshAccounts)

  const nameMap = useMemo(() => {
    const m = new Map<number, string>()
    for (const p of portfolios ?? []) if (p.id != null) m.set(p.id, p.name)
    return m
  }, [portfolios])

  // 首次加载：无数据时才 loading / 报错；已有数据则一直渲染（失联降级由顶栏体现）。
  if (accounts == null) {
    if (error) return <p className="text-[14px] text-bad">取数失败：{error.message}</p>
    return <p className="text-[14px] text-ink-2">加载中…</p>
  }

  if (accounts.length === 0) {
    return (
      <div className="rounded-card bg-surface p-8 text-center shadow-card">
        <p className="text-[15px] font-[620]">还没有账户</p>
        <p className="mt-2 text-[14px] text-ink-2">去设置向导创建第一个账户。</p>
      </div>
    )
  }

  if (accounts.length === 1) {
    return (
      <AccountDetail accountId={accounts[0].account_id} item={accounts[0]} onDashboardRefresh={refresh} />
    )
  }

  return <FleetView items={accounts} portfolioNames={nameMap} />
}
