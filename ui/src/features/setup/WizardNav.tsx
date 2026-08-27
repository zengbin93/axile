import { useState } from 'react'
import { useNavigate } from '@/components/ui/nav'
import type { ReactNode } from 'react'

/** 向导页容器：统一留白 + kicker/标题/引导语。宽屏统一 1080 自适应，两侧留白适度。 */
export function WizardPage({
  kicker,
  title,
  lead,
  children,
}: {
  kicker: string
  title: string
  lead?: string
  children?: ReactNode
}) {
  return (
    <div className="mx-auto max-w-[1080px] px-5 pt-8 pb-6 sm:px-12">
      <div className="mb-1.5 text-xs font-semibold tracking-wide text-accent">{kicker}</div>
      <div className="text-[22px] font-[680] tracking-tight">{title}</div>
      {lead && <div className="mt-1.5 max-w-[560px] text-[14px] text-ink-2">{lead}</div>}
      <div className="mt-[18px]">{children}</div>
    </div>
  )
}

/** 底部导航条：上一步 + 下一步（可自定义异步动作）。 */
export function WizardNav({
  prevTo,
  nextLabel = '下一步',
  nextTo,
  onNext,
  nextDisabled,
}: {
  prevTo?: string
  nextLabel?: string
  nextTo?: string
  onNext?: () => void | Promise<void>
  nextDisabled?: boolean
}) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  const handleNext = async () => {
    if (nextDisabled || busy) return
    if (onNext) {
      setBusy(true)
      try {
        await onNext()
      } finally {
        setBusy(false)
      }
    } else if (nextTo) {
      navigate(nextTo)
    }
  }

  const nextCls = 'bg-ink-1 border-ink-1 text-surface font-[550]'

  return (
    <div className="flex gap-3 border-t border-line bg-surface px-5 py-3.5 sm:px-12">
      {prevTo ? (
        <button
          className="cursor-pointer rounded-[11px] border border-line bg-surface px-[22px] py-2.5 text-[14px] text-ink-2"
          onClick={() => navigate(prevTo)}
        >
          上一步
        </button>
      ) : (
        <span />
      )}
      <span className="flex-1" />
      <button
        className={`cursor-pointer rounded-[11px] border px-[22px] py-2.5 text-[14px] disabled:opacity-45 ${nextCls}`}
        onClick={handleNext}
        disabled={nextDisabled || busy}
      >
        {busy ? '处理中…' : nextLabel}
      </button>
    </div>
  )
}
