import { useLayoutEffect, useRef, useState, type ReactElement } from 'react'

/** 分段控件的单个选项：值与显示文案分离。 */
export interface SegmentedOption<T extends string> {
  value: T
  label: string
}

/** 尺寸档：`md` 用于表单/配置页，`sm` 用于卡片角落等紧凑处。 */
type SegmentedSize = 'sm' | 'md'

/** 各尺寸的凹槽 / 滑块 / 按钮类片段。 */
const SIZE_CLASS: Record<SegmentedSize, { track: string; thumb: string; button: string }> = {
  md: { track: 'gap-1 rounded-[11px] p-1', thumb: 'top-1 bottom-1 rounded-lg', button: 'rounded-lg px-4 py-2 text-[14px]' },
  sm: { track: 'gap-0.5 rounded-[9px] p-0.5', thumb: 'top-0.5 bottom-0.5 rounded-md', button: 'rounded-md px-2.5 py-1 text-xs' },
}

/**
 * 「凹槽 + 滑块」分段控件（受控）。
 *
 * 高亮块是一个独立的 absolute 滑块，切换时平滑滑动，宽度随选中项文案变化。
 * 通过测量选中 button 的 offsetLeft / offsetWidth 定位滑块，配合 transform / width
 * 过渡实现动画。首帧直接就位、不做滑入；尊重系统「减少动态效果」。
 *
 * @typeParam T - 选项值的字面量联合类型。
 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = 'md',
  className = '',
}: {
  value: T
  options: SegmentedOption<T>[]
  onChange: (value: T) => void
  size?: SegmentedSize
  className?: string
}): ReactElement {
  const sz = SIZE_CLASS[size]
  const trackRef = useRef<HTMLDivElement>(null)
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([])
  const mountedRef = useRef(false)
  const [thumb, setThumb] = useState({ x: 0, w: 0 })

  const activeIndex = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  )

  useLayoutEffect(() => {
    const measure = () => {
      const el = btnRefs.current[activeIndex]
      if (!el) return
      setThumb({ x: el.offsetLeft, w: el.offsetWidth })
    }
    measure()
    mountedRef.current = true

    const track = trackRef.current
    if (!track) return
    const ro = new ResizeObserver(measure)
    ro.observe(track)
    return () => ro.disconnect()
  }, [activeIndex, options])

  return (
    <div
      ref={trackRef}
      className={`relative inline-flex bg-fill ${sz.track} ${className}`}
    >
      <span
        aria-hidden
        className={`absolute left-0 z-0 bg-surface shadow-sm ${sz.thumb} ${
          mountedRef.current
            ? 'transition-[transform,width] duration-200 ease-[cubic-bezier(.32,.72,0,1)] motion-reduce:transition-none'
            : ''
        }`}
        style={{ transform: `translateX(${thumb.x}px)`, width: `${thumb.w}px` }}
      />
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            btnRefs.current[i] = el
          }}
          type="button"
          className={`relative z-10 cursor-pointer transition-colors ${sz.button} ${
            o.value === value ? 'font-semibold text-ink-1' : 'text-ink-2'
          }`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
