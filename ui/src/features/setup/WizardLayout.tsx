import { Outlet, useLocation } from 'react-router'
import { Link } from '@/components/ui/nav'
import { Toast } from '@/components/Toast'
import { ThemeToggle } from '@/components/ThemeToggle'
import { flowOf, PF_STEPS, ACCT_STEPS, type Step } from '@/features/setup/steps'

function Rail({ steps, index, title }: { steps: Step[]; index: number; title: string }) {
  return (
    <aside className="w-[248px] flex-none overflow-y-auto border-r border-line bg-surface px-[18px] py-7">
      <div className="px-2.5 pb-3.5 text-xs font-semibold tracking-wide text-ink-3">{title}</div>
      {steps.map((s, i) => {
        const done = i < index
        const cur = i === index
        return (
          <Link
            key={s.path}
            to={s.path}
            className={`flex items-center gap-3 rounded-[10px] p-2.5 text-[14px] ${
              cur ? 'bg-accent-soft font-semibold text-ink-1' : 'text-ink-2'
            }`}
          >
            <span
              className={`grid h-6 w-6 flex-none place-items-center rounded-full border text-xs ${
                done
                  ? 'border-ok bg-ok text-white'
                  : cur
                    ? 'border-accent text-accent'
                    : 'border-border-strong bg-surface text-ink-3'
              }`}
            >
              {done ? '✓' : i + 1}
            </span>
            {s.label}
          </Link>
        )
      })}
    </aside>
  )
}

/** 向导外壳：独立全屏布局（头部 + 步骤栏 + 内容）。 */
export function WizardLayout() {
  const { pathname } = useLocation()
  const { flow, index } = flowOf(pathname)

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 flex-none items-center gap-3.5 border-b border-line bg-surface px-6">
        <Link to="/setup" className="font-[650] tracking-wide">
          axile
        </Link>
        <span className="text-[14px] text-ink-2">
          {flow === 'pf' ? '· 组合设置' : flow === 'acct' ? '· 账户设置' : ''}
        </span>
        <span className="ml-auto" />
        <ThemeToggle />
        <Link to="/" className="rounded-[9px] border border-line px-3.5 py-1.5 text-[13px] text-ink-2">
          关闭
        </Link>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {flow === 'pf' && <Rail steps={PF_STEPS} index={index} title="组合设置" />}
        {flow === 'acct' && <Rail steps={ACCT_STEPS} index={index} title="账户设置" />}
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </div>
      <Toast />
    </div>
  )
}
