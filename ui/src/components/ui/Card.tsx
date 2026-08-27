import type { CSSProperties, ReactNode } from 'react'

/** 仪表面板：surface 底 + hairline 边 + 小圆角，全站统一容器。层次靠线不靠影。 */
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
      className={`rounded-card border border-line bg-surface ${onClick ? 'cursor-pointer hover:border-border-strong' : ''} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  )
}

/** 小节标题（灰、字号 12、字距）。 */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mx-0.5 mt-2 mb-1 text-xs font-semibold tracking-wide text-ink-3">
      {children}
    </div>
  )
}

/** 圆角小胶囊标签。 */
export function Chip({
  children,
  className = '',
  style,
}: {
  children: ReactNode
  className?: string
  /** 共享元素 FLIP 等场景的直挂样式（viewTransitionName 由调用方按身份协议门控）。 */
  style?: CSSProperties
}) {
  return (
    <span
      className={`rounded-chip bg-fill px-2.5 py-[3px] text-xs text-ink-2 ${className}`}
      style={style}
    >
      {children}
    </span>
  )
}
