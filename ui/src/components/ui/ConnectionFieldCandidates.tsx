import { X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import type { ClipboardCandidate } from '@/components/ui/connectionFieldClipboard'

interface Position {
  left: number
  top: number
  width: number
}

interface Props {
  id: string
  label: string
  value: string
  mono: boolean
  candidates: ClipboardCandidate[]
  activeCandidate: number
  committingId: string | null
  pasteError: string | null
  anchorRef: RefObject<HTMLButtonElement | null>
  onActiveCandidate: (index: number) => void
  onCommit: (candidate: ClipboardCandidate) => void
  onClose: () => void
  onFillMatched?: () => void
}

const POPUP_GAP = 6
const POPUP_MARGIN = 12
const MOBILE_BOTTOM_CLEARANCE = 76

/** 智能粘贴的候选弹层；只负责定位、键鼠选择和批量动作。 */
export function ConnectionFieldCandidates({
  id,
  label,
  value,
  mono,
  candidates,
  activeCandidate,
  committingId,
  pasteError,
  anchorRef,
  onActiveCandidate,
  onCommit,
  onClose,
  onFillMatched,
}: Props) {
  const popupRef = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState<Position | null>(null)
  const hasMatched = candidates.some((candidate) => candidate.role)

  const place = useCallback(() => {
    const anchor = anchorRef.current
    if (!anchor) return
    const rect = anchor.getBoundingClientRect()
    const width = Math.min(400, window.innerWidth - POPUP_MARGIN * 2)
    const height = popupRef.current?.offsetHeight ?? 220
    if (window.innerWidth < 640) {
      setPosition({
        left: POPUP_MARGIN,
        top: Math.max(POPUP_MARGIN, window.innerHeight - height - MOBILE_BOTTOM_CLEARANCE),
        width,
      })
      return
    }
    const left = Math.max(POPUP_MARGIN, Math.min(rect.right - width, window.innerWidth - width - POPUP_MARGIN))
    const below = rect.bottom + POPUP_GAP
    const top = below + height <= window.innerHeight - POPUP_MARGIN
      ? below
      : Math.max(POPUP_MARGIN, rect.top - height - POPUP_GAP)
    setPosition({ left, top, width })
  }, [anchorRef])

  useLayoutEffect(() => {
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [candidates.length, place])

  useEffect(() => {
    const keydown = (event: globalThis.KeyboardEvent) => event.key === 'Escape' && onClose()
    const pointerdown = (event: PointerEvent) => {
      const target = event.target as Node
      if (popupRef.current?.contains(target) || anchorRef.current?.contains(target)) return
      onClose()
    }
    document.addEventListener('keydown', keydown)
    document.addEventListener('pointerdown', pointerdown)
    return () => {
      document.removeEventListener('keydown', keydown)
      document.removeEventListener('pointerdown', pointerdown)
    }
  }, [anchorRef, onClose])

  if (!position) return null
  return createPortal(
    <div
      ref={popupRef}
      id={`${id}-paste-candidates`}
      role="dialog"
      aria-label={`${label}本次粘贴候选`}
      className="select-pop-in fixed z-[60] overflow-hidden rounded-[8px] border border-line bg-surface p-2 shadow-card"
      style={{ left: position.left, top: position.top, width: position.width }}
    >
      <div className="flex min-h-8 items-center justify-between gap-2 px-1.5">
        <span className="truncate text-[12px] text-ink-2">从本次粘贴中识别到 {candidates.length} 项</span>
        <span className="flex flex-none items-center gap-0.5">
          {onFillMatched && hasMatched && (
            <button type="button" className="cursor-pointer px-1.5 text-[12px] text-accent hover:underline" onMouseDown={(event) => event.preventDefault()} onClick={onFillMatched}>
              填入已匹配项
            </button>
          )}
          <button type="button" title="关闭" aria-label="关闭本次粘贴候选" className="grid h-7 w-7 cursor-pointer place-items-center text-ink-3 hover:text-ink-1" onMouseDown={(event) => event.preventDefault()} onClick={onClose}>
            <X size={14} />
          </button>
        </span>
      </div>
      {pasteError && <div className="px-1.5 pb-1 text-[12px] text-warn">{pasteError}</div>}
      <div role="listbox" aria-label={`${label}本次粘贴候选列表`} className="mt-1 max-h-44 overflow-y-auto overscroll-contain">
        {candidates.map((candidate, index) => (
          <button
            key={candidate.id}
            type="button"
            role="option"
            aria-selected={index === activeCandidate}
            aria-label={candidate.kind === 'secret' ? candidate.displayValue : candidate.value}
            title={candidate.kind === 'secret' ? undefined : candidate.value}
            disabled={committingId !== null}
            className={`flex min-h-10 w-full cursor-pointer items-center gap-3 rounded-[6px] px-2 py-1.5 text-left disabled:cursor-wait ${index === activeCandidate ? 'bg-bg-subtle' : 'hover:bg-bg-subtle'}`}
            onMouseEnter={() => onActiveCandidate(index)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onCommit(candidate)}
          >
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[13px] text-ink-1 ${mono ? 'font-mono' : ''}`}>{candidate.displayValue}</span>
              {candidate.sourceLabel && (
                <span className={`mt-0.5 block truncate text-[11px] ${candidate.role ? 'text-accent' : 'text-ink-3'}`}>
                  {candidate.sourceLabel}
                </span>
              )}
            </span>
            <span className="flex-none text-[12px] text-ink-2">{value ? '替换' : '填入'}</span>
          </button>
        ))}
      </div>
    </div>,
    document.body,
  )
}
