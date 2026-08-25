import { useParams } from 'react-router'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { useDomainStore } from '@/stores/domain'
import { AccountDetail, AccountDetailSkeleton } from '@/features/account/AccountDetail'
import { ErrorNotice } from '@/components/ui/ErrorNotice'

/** 账户详情路由 /accounts/:id —— 从共享 store 读该账户，复用原子视图。 */
export function AccountDetailPage() {
  const { id } = useParams()
  const accountId = Number(id)
  const accounts = useDomainStore((s) => s.accounts)
  const error = useDomainStore((s) => s.accountsError)
  const refresh = useDomainStore((s) => s.refreshAccounts)

  const item = accounts?.find((a) => a.account_id === accountId)

  return (
    <section>
      <Breadcrumb trail={[{ label: item?.name ?? `账户 #${accountId}` }]} />
      <div className="mt-3">
        {accounts == null && !error && <AccountDetailSkeleton />}
        <ErrorNotice title="账户数据加载失败" error={accounts == null ? error : null} onRetry={refresh} />
        {accounts != null && !item && <p className="text-[14px] text-ink-3">未找到账户 #{accountId}。</p>}
        {item && <AccountDetail accountId={accountId} item={item} onDashboardRefresh={refresh} />}
      </div>
    </section>
  )
}
