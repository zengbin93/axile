import { useEffect, useRef, useState, type ComponentType, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { useLocation } from 'react-router'
import {
  Ban,
  BellRing,
  Boxes,
  ChartNoAxesCombined,
  ChevronDown,
  ChevronUp,
  CircleGauge,
  Layers3,
  ListChecks,
  Plus,
  Scale,
  Settings2,
  ShieldKeyhole,
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

function NavSection({
  label,
  children,
  compact = false,
}: {
  label: string
  children: ReactNode
  /** 账户块内部使用：组间距收紧，让块内多组读起来是一个整体。 */
  compact?: boolean
}) {
  return (
    <section className={compact ? 'mt-3.5 first:mt-0' : 'mt-5 first:mt-0'}>
      <div className="mb-1 truncate px-2.5 text-[11px] font-semibold tracking-[0.14em] text-ink-3" title={label}>
        {label}
      </div>
      <div>{children}</div>
    </section>
  )
}

/** 跟踪滚动容器两端是否还有被裁掉的内容，用于驱动边缘渐隐提示。 */
function useScrollEdges(ref: RefObject<HTMLElement | null>): { up: boolean; down: boolean } {
  const [edges, setEdges] = useState({ up: false, down: false })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const content = el.firstElementChild
    const update = () => {
      const remaining = el.scrollHeight - el.clientHeight - el.scrollTop
      const next = { up: el.scrollTop > 1, down: remaining > 1 }
      setEdges((prev) => (prev.up === next.up && prev.down === next.down ? prev : next))
    }
    update()
    el.addEventListener('scroll', update, { passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(el)
    if (content) observer.observe(content)
    return () => {
      el.removeEventListener('scroll', update)
      observer.disconnect()
    }
  }, [ref])
  return edges
}

/** 溢出端的方向提示：渐隐带 + 可点击箭头，点击按接近一屏的步长朝该端滚动。 */
function EdgeScrollHint({ edge, visible, target }: { edge: 'up' | 'down'; visible: boolean; target: RefObject<HTMLElement | null> }) {
  const Icon = edge === 'up' ? ChevronUp : ChevronDown
  const nudge = () => {
    const el = target.current
    if (!el) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollBy({
      top: (edge === 'up' ? -1 : 1) * el.clientHeight * 0.8,
      behavior: reduced ? 'auto' : 'smooth',
    })
  }
  return (
    <div
      aria-hidden={!visible}
      className={`pointer-events-none absolute inset-x-0 z-[2] flex h-10 from-surface via-surface/80 to-transparent transition-opacity duration-200 motion-reduce:transition-none ${
        edge === 'up' ? 'top-0 items-start bg-gradient-to-b' : 'bottom-0 items-end bg-gradient-to-t'
      } ${visible ? 'opacity-100' : 'opacity-0'}`}
    >
      <button
        type="button"
        aria-label={edge === 'up' ? '向上滚动导航' : '向下滚动导航'}
        tabIndex={visible ? 0 : -1}
        onClick={nudge}
        className={`mx-auto px-3 text-ink-3 transition-colors duration-150 hover:text-ink-1 ${edge === 'up' ? 'pt-1' : 'pb-1'} ${
          visible ? 'pointer-events-auto' : 'pointer-events-none'
        }`}
      >
        <Icon size={14} aria-hidden />
      </button>
    </div>
  )
}

function NavItem({ item }: { item: NavItemSpec }) {
  const location = useLocation()
  const active = item.active(location.pathname, location.hash)
  const Icon = item.icon
  const content = (
    <>
      {/* 游标：贴左缘的青色指示条，跨入口滑移（共享元素 FLIP）——「当前位置」是仪表上的游标，不是高亮块。 */}
      {active && (
        <span aria-hidden className="absolute top-1 bottom-1 left-0 w-[2.5px] rounded-full bg-accent" style={activeMarkerStyle} />
      )}
      <span className="relative z-[1] flex items-center gap-2.5">
        {Icon && <Icon size={15} aria-hidden />}
        <span>{item.label}</span>
      </span>
    </>
  )

  if (!item.to) {
    return (
      <span className="relative flex h-7.5 items-center gap-2 px-2.5 text-[13px] text-ink-3" aria-disabled="true">
        {content}
      </span>
    )
  }

  return (
    <Link
      to={item.to}
      aria-current={active ? 'page' : undefined}
      className={`relative flex h-7.5 items-center gap-2 px-2.5 text-[13px] transition-colors duration-150 motion-reduce:transition-none ${
        active ? 'font-[550] text-ink-1' : 'text-ink-2 hover:text-ink-1'
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
  // 组标题带上账户名：明示「这些条目属于哪个账户」，与顶层「所有账户」入口（列表落点）相区别。
  const activeName = accounts?.find((a) => a.account_id === accountId)?.name
  // 库里确定没有账户时收拢账户导航：三组入口此刻只有占位价值，一行说明它的归宿比 12 个禁用项安静。
  const noAccounts = accounts != null && accounts.length === 0 && accountId == null

  const navRef = useRef<HTMLElement>(null)
  const scrollEdges = useScrollEdges(navRef)

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
    { label: '连接设置', icon: ShieldKeyhole, to: accountPath('/edit/connection'), active: exact(accountPath('/edit/connection')) },
    { label: '杠杆设置', icon: Scale, to: accountPath('/edit/leverage'), active: exact(accountPath('/edit/leverage')) },
    { label: '品种控制', icon: Ban, to: accountPath('/edit/symbols'), active: exact(accountPath('/edit/symbols')) },
  ]
  const accountExecution: NavItemSpec[] = [
    { label: '定时节奏', icon: Timer, to: accountPath('/edit/timer'), active: exact(accountPath('/edit/timer')) },
    { label: '执行算法', icon: Workflow, to: accountPath('/edit/algorithm'), active: exact(accountPath('/edit/algorithm')) },
    { label: '执行流控', icon: SlidersHorizontal, to: accountPath('/edit/control'), active: exact(accountPath('/edit/control')) },
    { label: '绑定组合', icon: Layers3, to: accountPath('/edit/portfolio'), active: exact(accountPath('/edit/portfolio')) },
  ]

  return (
    <aside
      className="flex w-[218px] flex-none flex-col border-r border-line bg-surface py-3.5 pr-2.5 pl-3"
      aria-label="主导航"
    >
      <div className="relative flex min-h-0 flex-1 flex-col">
        <nav ref={navRef} className="quiet-scrollbar min-h-0 flex-1 overflow-y-auto pb-2" aria-label="功能导航">
          <div className="flex min-h-full flex-col justify-between">
            <div>
              <NavItem item={{ label: '所有账户', icon: CircleGauge, to: '/', active: (pathname) => pathname === '/' }} />
              <NavItem item={{ label: '所有组合', icon: Boxes, to: '/portfolios', active: (pathname) => pathname.startsWith('/portfolios') }} />

              {noAccounts ? (
                <NavSection label="当前账户">
                  <p className="px-2.5 py-1.5 text-[12px] leading-relaxed text-ink-3">
                    创建账户后，这里会出现它的持仓、参数与执行入口。
                  </p>
                </NavSection>
              ) : (
                /* 账户块：hairline 边 + 微沉底的内嵌面板，把「概览/参数/执行」三组
                   圈成一个整体——这些条目都属于同一个账户，与顶层列表入口相区别。 */
                <div className="mt-5 rounded-card border border-line bg-bg-subtle py-2 pl-1.5 pr-1">
                  <NavSection compact label={activeName ? `当前账户 · ${activeName}` : '当前账户'}>
                    {accountOverview.map((item) => <NavItem key={item.label} item={item} />)}
                  </NavSection>

                  <NavSection compact label="账户参数">
                    {accountParameters.map((item) => <NavItem key={item.label} item={item} />)}
                  </NavSection>

                  <NavSection compact label="自动执行">
                    {accountExecution.map((item) => <NavItem key={item.label} item={item} />)}
                  </NavSection>
                </div>
              )}

              <NavSection label="系统">
                <NavItem item={{ label: '飞书告警', icon: BellRing, to: '/settings', active: exact('/settings') }} />
                <NavItem item={{ label: '高级', icon: Settings2, to: '/settings/advanced', active: exact('/settings/advanced') }} />
              </NavSection>
            </div>
          </div>
        </nav>
        {/* 溢出揭示：被裁掉的一端用渐隐 + 方向箭头暗示「还有下文」，滚到顶/底即消失。常挂 + 透明度切换，不条件挂载。 */}
        <EdgeScrollHint edge="up" visible={scrollEdges.up} target={navRef} />
        <EdgeScrollHint edge="down" visible={scrollEdges.down} target={navRef} />
      </div>

      <div className="mt-3 border-t border-line pt-3">
        <div className="grid grid-cols-2 gap-1.5">
          <Link to="/setup/acct/channel" className="flex items-center justify-center gap-1.5 rounded-chip border border-line px-2 py-1.5 text-[12px] text-ink-2 hover:border-border-strong hover:text-ink-1">
            <Plus size={14} aria-hidden />新建账户
          </Link>
          <Link to="/setup/pf/name" className="flex items-center justify-center gap-1.5 rounded-chip border border-line px-2 py-1.5 text-[12px] text-ink-2 hover:border-border-strong hover:text-ink-1">
            <Plus size={14} aria-hidden />新建组合
          </Link>
        </div>
      </div>
    </aside>
  )
}
