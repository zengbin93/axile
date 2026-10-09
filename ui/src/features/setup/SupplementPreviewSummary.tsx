import NumberFlow from '@number-flow/react'
import { InkRewrite } from '@/components/ui/InkRewrite'
import { MOTION_LAYOUT } from '@/lib/viewTransition'

export interface SupplementPreviewValue {
  enabled: boolean
  count: number
  interval: number
}

const NUMBER_PROPS = {
  locales: 'zh-CN',
  format: { useGrouping: false },
  spinTiming: { duration: 220, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' },
  respectMotionPreference: true,
}

/** 摘要首次就位；数字在原槽滚动，开关仅改写补发标签。 */
export function SupplementPreviewSummary({ value, fallback }: { value?: SupplementPreviewValue; fallback: string }) {
  if (!value) return fallback
  const { enabled, count, interval } = value
  const text = enabled ? `补 ${count} 次${count > 0 ? ` · 隔 ${interval} 分` : ''}` : '不补发'
  return (
    <span aria-label={text} title={text} className="inline-flex max-w-full items-baseline justify-end align-baseline">
      <span aria-hidden="true"><InkRewrite text={enabled ? '补' : '不补发'} /></span>
      <span aria-hidden="true" className={`grid transition-[grid-template-columns] ${MOTION_LAYOUT} ${enabled ? 'grid-cols-[1fr]' : 'grid-cols-[0fr]'}`}>
        <span className="min-w-0 overflow-hidden">
          <span className="inline-flex w-max items-baseline whitespace-pre">
            <NumberFlow {...NUMBER_PROPS} value={count} prefix=" " suffix=" 次" animated={enabled} />
            <span className={count > 0 ? 'inline' : 'hidden'}>
              <NumberFlow {...NUMBER_PROPS} value={interval} prefix=" · 隔 " suffix=" 分" animated={enabled} />
            </span>
          </span>
        </span>
      </span>
    </span>
  )
}
