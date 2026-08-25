import { useEffect, type ComponentType, type CSSProperties, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import {
  Ban,
  BellRing,
  Boxes,
  CalendarDays,
  ChartNoAxesCombined,
  CircleGauge,
  Layers3,
  ListChecks,
  Plus,
  Scale,
  Settings2,
  SlidersHorizontal,
  Timer,
  UserRoundCog,
  WalletCards,
  Workflow,
} from 'lucide-react'
import { Link } from '@/components/ui/nav'
import { useDomainStore } from '@/stores/domain'
import { useNavigationStore } from '@/stores/ui'

interface NavItemSpec {
  label: string
  icon?: ComponentType<{ size?: number; 'aria-hidden'?: boolean }>
  to: string | null
  active: (pathname: string, hash: string) => boolean
}

const activeMarkerStyle: CSSProperties = { viewTransitionName: 'app-nav-selection' }

function accountIdFromPath(pathname: string): number | null {
  const matched = pathname.match(/^\/accounts\/(\d+)(?:\/|$)/)
  if (!matched) return null
  const accountId = Number(matched[1])
  return Number.isFinite(accountId) ? accountId : null
}

function NavSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-0.5 px-2.5 text-[11px] font-semibold tracking-wide text-ink-3">{label}</div>
      <div className="ml-3">{children}</div>
    </section>
  )
}

function NavItem({ item }: { item: NavItemSpec }) {
  const location = useLocation()
  const active = item.active(location.pathname, location.hash)
  const Icon = item.icon
  const content = (
    <>
      {active && (
        <span aria-hidden className="absolute inset-0 rounded-[7px] bg-accent-soft" style={activeMarkerStyle} />
      )}
      <span className="relative z-[1] flex items-center gap-2.5">
        {Icon && <Icon size={15} aria-hidden />}
        <span>{item.label}</span>
      </span>
    </>
  )

  if (!item.to) {
    return (
      <span className="relative flex h-7.5 items-center gap-2 rounded-[7px] px-2.5 text-[13px] text-ink-3" aria-disabled="true">
        {content}
      </span>
    )
  }

  return (
    <Link
      to={item.to}
      aria-current={active ? 'page' : undefined}
      className={`relative flex h-7.5 items-center gap-2 rounded-[7px] px-2.5 text-[13px] transition-colors duration-150 motion-reduce:transition-none ${
        active ? 'text-ink-1' : 'text-ink-2 hover:bg-bg-subtle hover:text-ink-1'
      }`}
    >
      {content}
    </Link>
  )
}

/** 悬浮式常驻导航：层级只表达归属，每个二级入口均直接抵达最终页面。 */
export function AppSidebar() {
  const location = useLocation()
  const accounts = useDomainStore((state) => state.accounts)
  const activeAccountId = useNavigationStore((state) => state.activeAccountId)
  const setActiveAccountId = useNavigationStore((state) => state.setActiveAccountId)
  const routeAccountId = accountIdFromPath(location.pathname)

  useEffect(() => {
    if (!accounts) return
    const ids = new Set(accounts.map((account) => account.account_id))
    const next = routeAccountId != null && ids.has(routeAccountId)
      ? routeAccountId
      : activeAccountId != null && ids.has(activeAccountId)
        ? activeAccountId
        : (accounts[0]?.account_id ?? null)
    if (next !== activeAccountId) setActiveAccountId(next)
  }, [accounts, routeAccountId, activeAccountId, setActiveAccountId])

  const accountId = routeAccountId ?? activeAccountId
  const accountPath = (suffix = '') => accountId == null ? null : `/accounts/${accountId}${suffix}`
  const exact = (to: string | null) => (pathname: string) => to != null && pathname === to

  const accountOverview: NavItemSpec[] = [
    { label: '账户概览', icon: CircleGauge, to: accountPath(), active: exact(accountPath()) },
    { label: '持仓明细', icon: WalletCards, to: accountPath('/holdings'), active: exact(accountPath('/holdings')) },
    {
      label: '执行记录',
      icon: ListChecks,
      to: accountPath('/executions'),
      active: (pathname) => pathname === accountPath('/executions') || pathname.startsWith(`${accountPath('/executions')}/`),
    },
    { label: '回看与绩效', icon: ChartNoAxesCombined, to: accountPath('/history'), active: exact(accountPath('/history')) },
  ]
  const accountParameters: NavItemSpec[] = [
    { label: '基本信息', icon: UserRoundCog, to: accountPath('/edit'), active: exact(accountPath('/edit')) },
    { label: '杠杆设置', icon: Scale, to: accountPath('/edit/leverage'), active: exact(accountPath('/edit/leverage')) },
    { label: '品种控制', icon: Ban, to: accountPath('/edit/symbols'), active: exact(accountPath('/edit/symbols')) },
  ]
  const accountExecution: NavItemSpec[] = [
    { label: '定时节奏', icon: Timer, to: accountPath('/edit/timer'), active: exact(accountPath('/edit/timer')) },
    { label: '执行算法', icon: Workflow, to: accountPath('/edit/algorithm'), active: exact(accountPath('/edit/algorithm')) },
    { label: '执行流控', icon: SlidersHorizontal, to: accountPath('/edit/control'), active: exact(accountPath('/edit/control')) },
    { label: '组合执行', icon: Layers3, to: accountPath('/edit/portfolio'), active: exact(accountPath('/edit/portfolio')) },
  ]

  return (
    <aside
      className="quiet-scrollbar absolute top-5 bottom-5 z-10 flex w-[224px] flex-col overflow-y-auto rounded-card bg-surface p-2.5 shadow-card"
      style={{ left: 'max(20px, calc(50% - 430px - 24px - 224px))' }}
      aria-label="主导航"
    >
      <nav className="flex flex-1 flex-col justify-between pb-2" aria-label="功能导航">
        <div>
          <NavItem item={{ label: '账户', icon: CircleGauge, to: '/', active: (pathname) => pathname === '/' }} />
          <NavItem item={{ label: '组合', icon: Boxes, to: '/portfolios', active: (pathname) => pathname.startsWith('/portfolios') }} />
        </div>

        <NavSection label="当前账户">
          {accountOverview.map((item) => <NavItem key={item.label} item={item} />)}
        </NavSection>

        <NavSection label="账户参数">
          {accountParameters.map((item) => <NavItem key={item.label} item={item} />)}
        </NavSection>

        <NavSection label="自动执行">
          {accountExecution.map((item) => <NavItem key={item.label} item={item} />)}
        </NavSection>

        <NavSection label="系统">
          <NavItem item={{ label: '交易日历', icon: CalendarDays, to: '/settings/trading-calendar', active: exact('/settings/trading-calendar') }} />
          <NavItem item={{ label: '飞书告警', icon: BellRing, to: '/settings', active: exact('/settings') }} />
          <NavItem item={{ label: '高级', icon: Settings2, to: '/settings/advanced', active: exact('/settings/advanced') }} />
        </NavSection>
      </nav>

      <div className="mt-auto border-t border-line pt-2">
        <div className="grid grid-cols-2 gap-1.5">
          <Link to="/setup/acct/channel" className="flex items-center justify-center gap-1.5 rounded-[9px] border border-line px-2 py-1.5 text-[12px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1">
            <Plus size={14} aria-hidden />新建账户
          </Link>
          <Link to="/setup/pf/name" className="flex items-center justify-center gap-1.5 rounded-[9px] border border-line px-2 py-1.5 text-[12px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1">
            <Plus size={14} aria-hidden />新建组合
          </Link>
        </div>
      </div>
    </aside>
  )
}
