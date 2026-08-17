/**
 * Mac 闹钟风格的时刻选择：双段大数字胶囊（时 | 分）。
 *
 * 点按打开双列滚轮；菜单经 portal 挂到 body，避免被祖先 overflow 裁切
 * （与 Select 同款策略）。着色仅用 theme token。
 */

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function parseHm(value: string): { h: number; m: number } | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!m) return null
  const h = Number(m[1])
  const min = Number(m[2])
  if (h < 0 || h > 23 || min < 0 || min > 59) return null
  return { h, m: min }
}

type Part = 'h' | 'm'

const ITEM_H = 36
const VISIBLE = 5
const GAP = 8

interface MenuPos {
  top: number
  left: number
  placement: 'down' | 'up'
}

/**
 * 单列数字滚轮（中间槽高亮）。
 */
function WheelColumn({
  max,
  value,
  onChange,
  labelledBy,
}: {
  max: number
  value: number
  onChange: (n: number) => void
  labelledBy: string
}) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const suppress = useRef(false)

  useEffect(() => {
    const el = scrollerRef.current
    if (!el || suppress.current) return
    const top = value * ITEM_H
    if (Math.abs(el.scrollTop - top) > 1) el.scrollTop = top
  }, [value])

  const settle = () => {
    const el = scrollerRef.current
    if (!el) return
    const idx = Math.max(0, Math.min(max, Math.round(el.scrollTop / ITEM_H)))
    suppress.current = true
    el.scrollTo({ top: idx * ITEM_H, behavior: 'smooth' })
    if (idx !== value) onChange(idx)
    window.setTimeout(() => {
      suppress.current = false
    }, 120)
  }

  const pad = Math.floor(VISIBLE / 2)

  return (
    <div className="relative w-[64px]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0.5 top-1/2 z-[1] h-9 -translate-y-1/2 rounded-[9px] bg-accent/15 shadow-[inset_0_0_0_1px_var(--color-accent)]"
      />
      <div
        ref={scrollerRef}
        role="listbox"
        aria-labelledby={labelledBy}
        aria-activedescendant={`${labelledBy}-${value}`}
        tabIndex={0}
        className="relative h-[180px] overflow-y-auto overscroll-contain [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        onScroll={() => {
          if (suppress.current) return
          const el = scrollerRef.current
          if (!el) return
          const idx = Math.max(0, Math.min(max, Math.round(el.scrollTop / ITEM_H)))
          if (idx !== value) onChange(idx)
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault()
            onChange(e.key === 'ArrowUp' ? Math.max(0, value - 1) : Math.min(max, value + 1))
          }
        }}
        onPointerUp={settle}
      >
        {Array.from({ length: pad }, (_, i) => (
          <div key={`t-${i}`} className="h-9 shrink-0" aria-hidden />
        ))}
        {Array.from({ length: max + 1 }, (_, n) => (
          <button
            key={n}
            type="button"
            id={`${labelledBy}-${n}`}
            role="option"
            aria-selected={n === value}
            className={`flex h-9 w-full shrink-0 cursor-pointer items-center justify-center font-mono text-[20px] font-[640] tabular-nums ${
              n === value ? 'text-ink-1' : 'text-ink-3'
            }`}
            onClick={() => onChange(n)}
          >
            {pad2(n)}
          </button>
        ))}
        {Array.from({ length: pad }, (_, i) => (
          <div key={`b-${i}`} className="h-9 shrink-0" aria-hidden />
        ))}
      </div>
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-12 bg-gradient-to-b from-surface to-transparent" />
      <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-surface to-transparent" />
    </div>
  )
}

/**
 * Mac 风格时刻选择器。
 */
export function MacTimePicker({
  value,
  onChange,
  className = '',
}: {
  value: string
  onChange: (value: string) => void
  className?: string
}): ReactElement {
  const parsed = parseHm(value)
  const h = parsed?.h ?? 8
  const m = parsed?.m ?? 0
  const empty = !parsed

  const [part, setPart] = useState<Part>('h')
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<MenuPos | null>(null)
  const triggerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const baseId = useId()

  const commit = useCallback(
    (nh: number, nm: number) => {
      onChange(`${pad2(nh)}:${pad2(nm)}`)
    },
    [onChange],
  )

  const ensureValue = () => {
    if (empty) commit(h, m)
  }

  const bump = (delta: number) => {
    ensureValue()
    if (part === 'h') commit((h + delta + 24) % 24, m)
    else commit(h, (m + delta + 60) % 60)
  }

  const place = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const menuH = 220
    const menuW = 160
    const spaceBelow = window.innerHeight - r.bottom
    const placement: 'down' | 'up' = spaceBelow < menuH + GAP && r.top > spaceBelow ? 'up' : 'down'
    let left = r.right - menuW
    left = Math.max(8, Math.min(left, window.innerWidth - menuW - 8))
    const top = placement === 'down' ? r.bottom + GAP : r.top - GAP - menuH
    setPos({ top, left, placement })
  }, [])

  const openMenu = (which: Part) => {
    setPart(which)
    ensureValue()
    place()
    setOpen(true)
  }

  useLayoutEffect(() => {
    if (!open) return
    place()
    const onScroll = () => place()
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  /** 一体胶囊：当前段 accent，另一段 fill；空值两段弱化。 */
  const segClass = (which: Part) => {
    if (empty && !open) return 'bg-transparent text-ink-3'
    if (part === which) return 'bg-accent text-white'
    return 'bg-transparent text-ink-1'
  }

  const menu =
    open &&
    pos &&
    createPortal(
      <div
        ref={menuRef}
        role="dialog"
        aria-label="选择时刻"
        className="select-pop-in fixed z-50 flex gap-2 rounded-[14px] border border-line bg-surface p-2.5 shadow-[0_12px_32px_rgba(0,0,0,0.18)]"
        style={{ top: pos.top, left: pos.left }}
      >
        <div className="flex flex-col items-center">
          <span id={`${baseId}-h`} className="mb-0.5 text-[11px] font-semibold tracking-wide text-ink-3">
            时
          </span>
          <WheelColumn
            max={23}
            value={h}
            labelledBy={`${baseId}-h`}
            onChange={(nh) => {
              setPart('h')
              commit(nh, m)
            }}
          />
        </div>
        <div className="w-px self-stretch bg-line" aria-hidden />
        <div className="flex flex-col items-center">
          <span id={`${baseId}-m`} className="mb-0.5 text-[11px] font-semibold tracking-wide text-ink-3">
            分
          </span>
          <WheelColumn
            max={59}
            value={m}
            labelledBy={`${baseId}-m`}
            onChange={(nm) => {
              setPart('m')
              commit(h, nm)
            }}
          />
        </div>
      </div>,
      document.body,
    )

  return (
    <div className={`inline-flex ${className}`}>
      <div
        ref={triggerRef}
        role="group"
        aria-label="时刻"
        aria-expanded={open}
        tabIndex={0}
        className="inline-flex overflow-hidden rounded-[12px] bg-fill outline-none focus-visible:shadow-[0_0_0_2px_var(--color-accent)]"
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp') {
            e.preventDefault()
            bump(1)
          } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            bump(-1)
          } else if (e.key === 'ArrowLeft') {
            e.preventDefault()
            setPart('h')
          } else if (e.key === 'ArrowRight') {
            e.preventDefault()
            setPart('m')
          } else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            if (open) setOpen(false)
            else openMenu(part)
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
        onWheel={(e) => {
          if (open) return
          if (Math.abs(e.deltaY) < 1) return
          e.preventDefault()
          bump(e.deltaY > 0 ? -1 : 1)
        }}
      >
        <button
          type="button"
          aria-label="时"
          aria-pressed={part === 'h'}
          onClick={() => openMenu('h')}
          className={`min-w-[3.4rem] px-3.5 py-2.5 font-mono text-[28px] font-[640] leading-none tabular-nums tracking-tight transition-colors ${segClass('h')}`}
        >
          {empty && !open ? '––' : pad2(h)}
        </button>
        <button
          type="button"
          aria-label="分"
          aria-pressed={part === 'm'}
          onClick={() => openMenu('m')}
          className={`min-w-[3.4rem] px-3.5 py-2.5 font-mono text-[28px] font-[640] leading-none tabular-nums tracking-tight transition-colors ${segClass('m')}`}
        >
          {empty && !open ? '––' : pad2(m)}
        </button>
      </div>
      {menu}
    </div>
  )
}
