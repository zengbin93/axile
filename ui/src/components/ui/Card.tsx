import type { ReactNode } from 'react'

/** 白底圆角卡片，全站统一容器。 */
export function Card({
  children,
  className = '',
  onClick,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
}) {
  return (
    <div
      className={`rounded-card bg-surface shadow-card ${onClick ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  )
}

/** 小节标题（灰、字号 12、字距）。 */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mx-0.5 mt-6 mb-3 text-xs font-semibold tracking-wide text-ink-3">
      {children}
    </div>
  )
}

/** 圆角小胶囊标签。 */
export function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`rounded-chip bg-fill px-2.5 py-[3px] text-xs text-ink-2 ${className}`}
    >
      {children}
    </span>
  )
}
