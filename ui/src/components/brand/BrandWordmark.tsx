/**
 * axile 品牌字标：纯文字，无图标。
 *
 * Space Grotesk 620 + 收紧字距的现代几何排布；「i」的圆点染 accent 青——
 * 整个字标里唯一的一点颜色，是品牌的记忆点。
 */
export function BrandWordmark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <span
      className={`font-[620] leading-none tracking-[-0.015em] ${className ?? ''}`}
      style={{ fontSize: size }}
    >
      ax<span style={{ color: 'var(--color-accent)' }}>i</span>le
    </span>
  )
}
