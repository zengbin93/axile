import { useState } from 'react'
import { useViewTransitionState } from 'react-router'
import { Link, useNavigate } from '@/components/ui/nav'
import { Breadcrumb } from '@/components/ui/Breadcrumb'
import { Card, Chip } from '@/components/ui/Card'
import { ConfirmModal, type ConfirmSpec } from '@/components/ui/ConfirmModal'
import { deletePortfolio } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import { useToastStore } from '@/stores/ui'
import type { AccountDashboardItem, PortfolioLite } from '@/types/api'

/** 组合列表 /portfolios —— 组合的「家」，保证每个组合始终可达 + 管理入口。 */
export function PortfoliosPage() {
  const navigate = useNavigate()
  const toast = useToastStore((s) => s.toast)
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null)

  const portfolios = useDomainStore((s) => s.portfolios)
  const accounts = useDomainStore((s) => s.accounts)
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
        try {
          await deletePortfolio(p.id!)
          toast('组合已删除')
          void refreshPortfolios()
        } catch (e) {
          toast(`删除失败：${e instanceof Error ? e.message : String(e)}`)
        }
      },
    })
  }

  const list = portfolios ?? []

  return (
    <section>
      <Breadcrumb trail={[{ label: '组合' }]} />
      <div className="mt-3 mb-4 flex items-center justify-between">
        <h1 className="text-[18px] font-[640]">组合</h1>
        <Link
          to="/setup/pf/name"
          className="cursor-pointer rounded-[9px] border-0 bg-ink-1 px-4 py-2 text-[13.5px] font-[550] text-surface"
        >
          ＋ 新建组合
        </Link>
      </div>

      {portfolios == null && <p className="text-[14px] text-ink-2">加载中…</p>}

      {portfolios != null && list.length === 0 && (
        <Card className="p-8 text-center">
          <p className="text-[15px] font-[620]">还没有组合</p>
          <p className="mt-2 text-[14px] text-ink-2">组合是「交易什么」的来源，可被多个账户复用。</p>
          <Link to="/setup/pf/name" className="mt-4 inline-block text-[14px] font-semibold text-accent">
            新建组合 →
          </Link>
        </Card>
      )}

      {list.map((p) => (
        <PortfolioCard key={p.id} p={p} followers={followersOf(p.id)} onDelete={askDelete} />
      ))}

      <ConfirmModal spec={confirm} onClose={() => setConfirm(null)} />
    </section>
  )
}

/** 组合列表卡。抽成组件以便每卡独立用 useViewTransitionState 挂共享名（共享元素 FLIP）。 */
function PortfolioCard({
  p,
  followers,
  onDelete,
}: {
  p: PortfolioLite
  followers: AccountDashboardItem[]
  onDelete: (p: PortfolioLite) => void
}) {
  const navigate = useNavigate()
  const to = `/portfolios/${p.id}`
  // 仅「正在跳去本组合详情」时给组合名挂共享名，与详情头配对做平移放大。
  const nameVt = useViewTransitionState(to)
  return (
    <Card
      className="mb-3 flex items-center gap-4 px-6 py-4 transition-transform hover:-translate-y-px"
      onClick={() => navigate(to)}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <span
            className="text-[15px] font-[620]"
            style={nameVt && p.id != null ? { viewTransitionName: `portfolio-name-${p.id}` } : undefined}
          >
            {p.name}
          </span>
          <Chip>{p.market}</Chip>
          <Chip>{p.custom_calc_py_code ? '自定义逻辑' : '策略组合'}</Chip>
        </div>
        <div className="mt-1 text-[12.5px] text-ink-3">
          {followers.length > 0 ? (
            <span className="text-ink-2">跟随 · {followers.map((f) => f.name).join('、')}</span>
          ) : (
            '未绑定账户'
          )}
          {' · 更新 '}
          {p.updated_at.replace('T', ' ').slice(0, 16)}
        </div>
      </div>
      <div className="flex flex-none items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          className="cursor-pointer rounded-lg border border-line px-3 py-1.5 text-[12.5px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
          onClick={() => navigate(to + '/edit')}
        >
          编辑
        </button>
        <button
          className="cursor-pointer rounded-lg border border-line px-3 py-1.5 text-[12.5px] text-ink-2 hover:border-bad/40 hover:text-bad"
          onClick={() => onDelete(p)}
        >
          删除
        </button>
      </div>
    </Card>
  )
}
