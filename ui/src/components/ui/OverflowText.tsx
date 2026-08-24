import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'

import {
  OVERFLOW_TEXT_DELAY_MS,
  overflowTextDistance,
  overflowTextDuration,
} from '@/components/ui/overflowTextMotion'

type OverflowTextStyle = CSSProperties & {
  '--overflow-text-delay': string
  '--overflow-text-distance': string
  '--overflow-text-duration': string
}

interface OverflowTextProps {
  /** 单行显示的完整文本。 */
  text: string
  /** 槽位的布局、字色与排版类；组件自身负责单行裁切。 */
  className?: string
}

/**
 * 单行溢出文本：静态时显示省略号，悬停后在原槽内播放完整内容。
 *
 * 静态层维持原有行高与省略号；播放层绝对定位，不参与布局。只有实测溢出时才挂动效，
 * 系统偏好减少动态效果时保留静态省略，并用原生 title 提供完整文本。
 */
export function OverflowText({ text, className = '' }: OverflowTextProps) {
  const viewportRef = useRef<HTMLSpanElement>(null)
  const contentRef = useRef<HTMLSpanElement>(null)
  const [distance, setDistance] = useState(0)
  const [reduceMotion, setReduceMotion] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  )

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    const content = contentRef.current
    if (!viewport || !content) return

    let active = true
    const measure = () => {
      if (!active) return
      setDistance((current) => {
        const measured = overflowTextDistance(content.offsetWidth, viewport.clientWidth)
        return measured === current ? current : measured
      })
    }

    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    observer.observe(content)
    void document.fonts?.ready.then(measure)
    return () => {
      active = false
      observer.disconnect()
    }
  }, [text])

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!media) return
    const update = () => setReduceMotion(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  const duration = overflowTextDuration(distance)
  const style: OverflowTextStyle = {
    '--overflow-text-delay': `${OVERFLOW_TEXT_DELAY_MS}ms`,
    '--overflow-text-distance': `${distance}px`,
    '--overflow-text-duration': `${duration}ms`,
  }
  const overflowed = distance > 0

  return (
    <span
      ref={viewportRef}
      className={`overflow-text relative block min-w-0 ${className}`.trim()}
      data-overflow={overflowed ? 'true' : 'false'}
      style={style}
      title={overflowed && reduceMotion ? text : undefined}
    >
      <span className="overflow-text-static block truncate">{text}</span>
      <span className="overflow-text-motion pointer-events-none invisible absolute inset-0 overflow-hidden" aria-hidden>
        <span ref={contentRef} key={text} className="overflow-text-track block w-max min-w-full whitespace-nowrap">
          {text}
        </span>
      </span>
    </span>
  )
}
