import { useEffect, useId, useRef } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { FEE_OPTIONS, feeOption } from '@/features/history/performance'

const PRESETS = FEE_OPTIONS.filter(option => option.value !== 'custom')

export function FeeControl({ fee, onChange, onEditingChange }: { fee: string; onChange: (fee: string) => void; onEditingChange: (editing: boolean) => void }) {
  const id = useId()
  const menuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const selected = feeOption(fee)
  useEffect(() => {
    const dismiss = () => menuRef.current?.hidePopover()
    window.addEventListener('resize', dismiss)
    window.addEventListener('scroll', dismiss, true)
    return () => {
      window.removeEventListener('resize', dismiss)
      window.removeEventListener('scroll', dismiss, true)
    }
  }, [])
  return <div role="group" aria-label="单边费率 BP" className="flex min-w-0 flex-wrap items-center gap-2">
    <span className="shrink-0 text-xs text-ink-3">单边费率</span>
    <div className="relative flex h-8 w-36 shrink-0 items-center rounded border border-line bg-surface text-xs text-ink-3 focus-within:border-accent">
        <input ref={inputRef} aria-label="单边费率（BP）" type="text" inputMode="decimal" autoComplete="off" value={fee}
          onFocus={() => onEditingChange(true)} onBlur={() => onEditingChange(false)}
          onChange={event => onChange(event.target.value)}
          className="num h-full min-w-0 flex-1 bg-transparent px-2 text-sm text-ink-1 outline-none" />
        <span>BP</span>
        <button type="button" popoverTarget={id} aria-label="常用费率" title="常用费率" aria-haspopup="menu"
          className="flex h-full w-8 shrink-0 items-center justify-center rounded-r text-ink-3 hover:text-ink-1 focus-visible:outline-accent"
          onClick={event => {
            const box = event.currentTarget.parentElement!.getBoundingClientRect()
            const menu = menuRef.current!
            menu.style.left = `${box.left}px`
            menu.style.top = `${box.bottom + 6}px`
            menu.style.width = `${box.width}px`
          }}>
          <ChevronDown size={14} />
        </button>
        <div ref={menuRef} id={id} popover="auto" role="menu" aria-label="常用费率"
          className="fixed m-0 rounded-lg border border-line bg-surface p-1 text-sm text-ink-2 shadow-card"
          onToggle={event => {
            if (event.newState === 'open') {
              const menu = menuRef.current
              const active = menu?.querySelector<HTMLButtonElement>('[aria-checked="true"]') ?? menu?.querySelector('button')
              active?.focus({ preventScroll: true })
            }
          }}
          onKeyDown={event => {
            const buttons = Array.from(event.currentTarget.querySelectorAll('button'))
            const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
              event.preventDefault()
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length
              buttons[next]?.focus()
            }
            if (event.key === 'Tab') menuRef.current?.hidePopover()
          }}>
          {PRESETS.map(option => <button key={option.value} type="button" role="menuitemradio" aria-checked={selected === option.value}
            className="flex w-full items-center justify-between gap-3 rounded px-2 py-2 text-left hover:bg-fill focus:bg-fill focus:outline-none"
            onClick={() => {
              onChange(option.value)
              menuRef.current?.hidePopover()
              inputRef.current?.focus()
            }}>
            <span className="num">{option.label} BP</span>
            <Check size={14} className={selected === option.value ? 'text-ink-1' : 'invisible'} />
          </button>)}
        </div>
    </div>
  </div>
}
