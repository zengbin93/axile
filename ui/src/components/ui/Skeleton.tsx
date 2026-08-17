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
  return <div className={`animate-pulse rounded-md bg-fill ${className}`} />
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
