/**
 * axile 基础商标。
 *
 * 概念「轴上两点」：两条 hairline 轴定出坐标系（axile 与 axis 同源——目标权重的
 * 坐标系），近处一个暗点是当前持仓，远处一个青点是目标权重——产品做的事就是把
 * 前者推向后者。轴线继承 currentColor，目标点固定 accent，随主题自然适配。
 */
export function AxileMark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className={className}
    >
      {/* 坐标轴：原点在左下，留出右上象限讲故事 */}
      <path d="M4 19.75h16.25" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.55" />
      <path d="M4.25 4v15.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.55" />
      {/* 当前持仓：暗点，贴着轴 */}
      <circle cx="9" cy="15" r="2.1" fill="currentColor" opacity="0.8" />
      {/* 目标权重：青点，更远更亮 */}
      <circle cx="16.25" cy="7.75" r="2.7" fill="var(--accent)" />
    </svg>
  )
}

/** 完整 lockup：mark + wordmark。wordmark 用品牌字 Space Grotesk，全小写。 */
export function AxileLogo({ size = 15, mark = 20, className }: { size?: number; mark?: number; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 text-ink-1 ${className ?? ''}`}>
      <AxileMark size={mark} />
      <span
        className="font-[620] leading-none tracking-[-0.01em]"
        style={{ fontSize: size }}
      >
        axile
      </span>
    </span>
  )
}
