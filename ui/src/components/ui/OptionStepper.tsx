import NumberFlow from '@number-flow/react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { KeyboardEvent } from 'react'

const SPIN_TIMING = { duration: 220, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' }
const TRANSFORM_TIMING = { duration: 180, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }
const OPACITY_TIMING = { duration: 160, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }
const NUMBER_FORMAT = { useGrouping: false }

export interface OptionStepperProps {
  value: number
  /** 从小到大排列的可选档位；当前值可以来自列表之外的已有配置。 */
  options: readonly number[]
  onChange: (value: number) => void
  ariaLabel: string
  unit?: string
  zeroLabel?: string
  disabled?: boolean
  /** 行内模式由外层组合控件提供边框。 */
  appearance?: 'boxed' | 'inline'
}

/** 离散数值步进：左右切换相邻档位，保留已有值，边界按钮禁用。 */
export function OptionStepper({ value, options, onChange, ariaLabel, unit, zeroLabel, disabled = false, appearance = 'boxed' }: OptionStepperProps) {
  const inline = appearance === 'inline'
  const showZeroLabel = value === 0 && zeroLabel != null
  const label = showZeroLabel ? zeroLabel : `${value}${unit ? ` ${unit}` : ''}`
  const previous = options.filter((option) => option < value).at(-1)
  const next = options.find((option) => option > value)
  const change = (target: number | undefined) => {
    if (!disabled && target !== undefined && target !== value) onChange(target)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return
    switch (event.key) {
      case 'ArrowLeft':
      case 'ArrowDown':
        event.preventDefault()
        change(previous)
        break
      case 'ArrowRight':
      case 'ArrowUp':
        event.preventDefault()
        change(next)
        break
      case 'Home':
        event.preventDefault()
        change(options[0])
        break
      case 'End':
        event.preventDefault()
        change(options.at(-1))
        break
    }
  }
  const buttonClass = `grid h-full ${inline ? 'w-6 rounded-md' : 'w-9'} shrink-0 cursor-pointer place-items-center text-ink-3 transition-colors hover:bg-fill hover:text-ink-1 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-ink-3 motion-reduce:transition-none`
  return (
    <div onKeyDown={onKeyDown} className={inline ? 'inline-flex h-9 shrink-0 items-center' : 'inline-flex h-10 items-center overflow-hidden rounded-[9px] border border-line bg-surface focus-within:border-accent'}>
      <button type="button" aria-label={`上一档${ariaLabel}`} disabled={disabled || previous === undefined} onClick={() => change(previous)} className={buttonClass}>
        <ChevronLeft size={16} aria-hidden="true" />
      </button>
      <div role="spinbutton" tabIndex={disabled ? -1 : 0} aria-label={ariaLabel} aria-valuenow={value}
        aria-valuemin={options[0]} aria-valuemax={Math.max(value, options.at(-1) ?? value)} aria-valuetext={label} aria-disabled={disabled || undefined}
        className={`num grid h-full ${inline ? 'w-10 rounded-md' : 'w-16'} shrink-0 place-items-center text-sm text-ink-1 outline-none focus-visible:bg-fill`}>
        <span aria-hidden="true" className="relative inline-grid place-items-center">
          <NumberFlow value={value} locales="zh-CN" format={NUMBER_FORMAT} suffix={unit ? ` ${unit}` : undefined}
            spinTiming={SPIN_TIMING} transformTiming={TRANSFORM_TIMING} opacityTiming={OPACITY_TIMING}
            respectMotionPreference className={showZeroLabel ? 'invisible' : undefined} />
          {showZeroLabel && <span className="absolute inset-0 grid place-items-center whitespace-nowrap">{zeroLabel}</span>}
        </span>
      </div>
      <button type="button" aria-label={`下一档${ariaLabel}`} disabled={disabled || next === undefined} onClick={() => change(next)} className={buttonClass}>
        <ChevronRight size={16} aria-hidden="true" />
      </button>
    </div>
  )
}
