import { useEffect, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import { useThemeStore, type ThemeMode } from '@/stores/theme'

const SunIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
)
const MoonIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </svg>
)
const AutoIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </svg>
)
const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M20 6 9 17l-5-5" />
  </svg>
)

const OPTIONS: { mode: ThemeMode; label: string; Icon: () => ReactElement }[] = [
  { mode: 'light', label: '浅色', Icon: SunIcon },
  { mode: 'dark', label: '深色', Icon: MoonIcon },
  { mode: 'system', label: '跟随系统', Icon: AutoIcon },
]

/** 当前是否呈深色（用于触发按钮图标）。 */
function effectiveDark(mode: ThemeMode): boolean {
  return mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
}

/** 主题切换：单图标触发 + 三态下拉菜单（浅 / 深 / 跟随系统）。 */
export function ThemeToggle() {
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const Trigger = effectiveDark(mode) ? MoonIcon : SunIcon

  return (
    <div className="relative" ref={ref}>
      <button
        className="flex cursor-pointer items-center rounded-chip border border-line px-2.5 py-1.5 text-ink-2 hover:border-ink-3/40 hover:text-ink-1"
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        title="主题"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="切换主题"
      >
        <Trigger />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-[37] mt-1.5 min-w-[150px] rounded-xl border border-line bg-surface p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.16)]"
        >
          {OPTIONS.map((o) => (
            <button
              key={o.mode}
              role="menuitemradio"
              aria-checked={mode === o.mode}
              className="flex w-full cursor-pointer items-center gap-2.5 rounded-lg border-0 bg-transparent px-2.5 py-2 text-left text-[13.5px] text-ink-1 hover:bg-fill"
              onClick={() => {
                setMode(o.mode)
                setOpen(false)
              }}
            >
              <span className={mode === o.mode ? 'text-accent' : 'text-ink-3'}>
                <o.Icon />
              </span>
              <span className="flex-1">{o.label}</span>
              {mode === o.mode && (
                <span className="text-accent">
                  <CheckIcon />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
