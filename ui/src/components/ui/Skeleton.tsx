import type { ReactNode } from 'react'

/**
 * 骨架占位。
 *
 * 冷拉页在数据到达前渲染与成品「同尺寸」的灰块，替代整屏「加载中…」文字——
 * 页面高度不塌陷、切换不闪空（L1 消闪）。仅是布局占位，不承载语义。
 */
interface SkeletonProps {
  /** 额外类名，通常用来指定宽高（如 `h-6 w-40`）。 */
  className?: string
}

/** 单个脉冲灰块。 */
export function Skeleton({ className = '' }: SkeletonProps) {
  return <div aria-hidden className={`animate-pulse rounded-md bg-fill motion-reduce:animate-none ${className}`} />
}

/** 行内文字槽骨架；宽度由调用处按成品文字指定。 */
export function SkeletonText({ className = '' }: SkeletonProps) {
  return <Skeleton className={`inline-block h-[1em] align-middle ${className}`} />
}

/** 给一组纯视觉骨架补充统一的 busy 语义。 */
export function SkeletonGroup({
  label,
  className = '',
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <div aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  )
}

/** 多行等宽骨架（末行略短，贴近真实文本块）。 */
export function SkeletonLines({ rows = 3, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`flex flex-col gap-2.5 ${className}`}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`h-4 ${i === rows - 1 ? 'w-2/3' : 'w-full'}`} />
      ))}
    </div>
  )
}
