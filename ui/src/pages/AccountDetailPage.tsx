import { useParams } from 'react-router'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { useDomainStore } from '@/stores/domain'
import { AccountDetail } from '@/features/account/AccountDetail'

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
        {accounts == null && !error && <p className="text-[14px] text-ink-2">加载中…</p>}
        {accounts == null && error && <p className="text-[14px] text-bad">取数失败：{error.message}</p>}
        {accounts != null && !item && <p className="text-[14px] text-ink-3">未找到账户 #{accountId}。</p>}
        {item && <AccountDetail accountId={accountId} item={item} onDashboardRefresh={refresh} />}
      </div>
    </section>
  )
}
