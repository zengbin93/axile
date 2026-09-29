import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

/** 工作台内可折叠面板的统一外壳；高度轨道由所在工作台分配。 */
export function WorkbenchPanel({
  title,
  open,
  onToggle,
  headerExtra,
  status,
  children,
  className,
  bodyClassName,
  stale = false,
}: {
  title: string
  open: boolean
  onToggle: () => void
  headerExtra?: ReactNode
  status?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  stale?: boolean
}) {
  return (
    <section
      aria-label={title}
      className={`row-span-2 grid min-h-0 overflow-hidden bg-surface [grid-template-rows:subgrid] ${className ?? ''}`}
    >
      <header className={`flex h-9 flex-none items-stretch ${open ? 'border-b border-line' : ''}`}>
        <button
          type="button"
          aria-expanded={open}
          className={`flex cursor-pointer items-center gap-1.5 px-3.5 text-[12px] font-semibold tracking-wide text-ink-1 ${open ? 'border-b border-accent' : ''}`}
          onClick={onToggle}
        >
          <ChevronDown
            size={13}
            aria-hidden
            className={`text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${open ? '' : '-rotate-90'}`}
          />
          {title}
        </button>
        {headerExtra}
        {status}
      </header>
      <div
        inert={!open}
        className={`min-h-0 flex-1 overflow-auto [scrollbar-gutter:stable] ${bodyClassName ?? 'px-3.5 py-3'} ${stale ? 'opacity-55' : ''}`}
      >
        {children}
      </div>
    </section>
  )
}
