import { Outlet, useLocation } from 'react-router'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Link, useNavigate } from '@/components/ui/nav'

const SETTINGS_NAV = [
  { to: '/settings', label: '飞书告警', exact: true },
] as const

/** 设置中心共享外壳：桌面侧栏、移动端横向导航，以及统一的页面级操作。 */
export function SettingsLayout() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <div className="flex h-screen flex-col bg-bg">
      <header className="flex h-14 flex-none items-center gap-3.5 border-b border-line bg-surface px-4 sm:px-6">
        <span className="font-[650] tracking-wide">axile</span>
        <span className="text-[14px] text-ink-2">· 设置</span>
        <span className="ml-auto" />
        <ThemeToggle />
        <button
          className="cursor-pointer rounded-chip border border-line px-3 py-1.5 text-[13px] text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
          onClick={() => navigate('/')}
        >
          关闭
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        <aside className="flex w-full flex-none overflow-x-auto border-b border-line bg-surface px-3 py-2 sm:block sm:w-[248px] sm:border-r sm:border-b-0 sm:px-[18px] sm:py-7">
          <div className="hidden px-2.5 pb-3.5 text-xs font-semibold tracking-wide text-ink-3 sm:block">设置</div>
          {SETTINGS_NAV.map((item) => {
            const active = item.exact
              ? location.pathname === item.to
              : location.pathname.startsWith(item.to)
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={`flex min-w-fit flex-none items-center rounded-[8px] px-3 py-2.5 text-[14px] sm:mb-1 sm:w-full ${
                  active ? 'bg-accent-soft font-semibold text-ink-1' : 'text-ink-2 hover:text-ink-1'
                }`}
              >
                {item.label}
              </Link>
            )
          })}
        </aside>

        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
