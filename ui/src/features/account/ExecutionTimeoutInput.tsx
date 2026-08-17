import NumberFlow from '@number-flow/react'
import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ExecutionTimeoutHelp } from '@/features/account/ExecutionTimeoutHelp'
import { stepExecutionTimeout } from '@/features/account/executionTimeout'

const SPIN_TIMING = { duration: 220, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' }
const TRANSFORM_TIMING = { duration: 180, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }
const OPACITY_TIMING = { duration: 160, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }
const NUMBER_FORMAT = { useGrouping: false }

interface ExecutionTimeoutInputProps {
  id?: string
  value: string
  onChange: (value: string) => void
  describedBy?: string
  invalid?: boolean
}

/** 可直接输入、亦可按 30 秒步进的账户执行超时控件。 */
export function ExecutionTimeoutInput({
  id,
  value,
  onChange,
  describedBy,
  invalid = false,
}: ExecutionTimeoutInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isEditing, setIsEditing] = useState(false)
  const parsedValue = Number(value)
  const validValue =
    value.trim() !== '' && Number.isInteger(parsedValue) && parsedValue >= 1 && parsedValue <= 540
      ? parsedValue
      : null
  const lastValidValue = useRef(validValue ?? 1)
  if (validValue !== null) lastValidValue.current = validValue

  const showInput = isEditing || invalid || validValue === null
  const decreaseValue = stepExecutionTimeout(value, -1)
  const increaseValue = stepExecutionTimeout(value, 1)
  const decreaseDisabled = decreaseValue === value
  const increaseDisabled = increaseValue === value

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const next = event.key === 'ArrowUp' ? increaseValue : decreaseValue
    if (next !== value) onChange(next)
  }

  const applyStep = (next: string) => {
    if (next === value) return
    setIsEditing(false)
    onChange(next)
  }

  const stepButton =
    'grid h-full w-9 flex-none place-items-center border-0 bg-transparent text-[18px] text-ink-3 transition-colors hover:bg-fill hover:text-ink-1 disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-ink-3'

  return (
    <div className="flex items-center gap-1.5">
      <div
        className={`flex h-10 overflow-hidden rounded-[9px] border bg-surface ${
          invalid ? 'border-warn focus-within:border-warn' : 'border-ink-3/30 focus-within:border-ink-2'
        }`}
      >
        <button
          type="button"
          aria-label="减少 30 秒"
          title="减少 30 秒"
          className={`${stepButton} border-r border-r-line`}
          disabled={decreaseDisabled}
          onClick={() => applyStep(decreaseValue)}
        >
          −
        </button>
        <div className="relative min-w-[88px] cursor-text px-2">
          <div
            aria-hidden="true"
            className={`pointer-events-none absolute inset-0 flex items-center justify-center gap-1 ${
              showInput ? 'opacity-0' : 'opacity-100'
            }`}
          >
            <NumberFlow
              value={lastValidValue.current}
              locales="zh-CN"
              format={NUMBER_FORMAT}
              className="num text-[15px] text-ink-1"
              spinTiming={SPIN_TIMING}
              transformTiming={TRANSFORM_TIMING}
              opacityTiming={OPACITY_TIMING}
              respectMotionPreference
            />
            <span className="flex-none text-[12px] text-ink-3">秒</span>
          </div>
          <div
            className={`relative flex h-full items-center justify-center gap-1 ${
              showInput ? 'opacity-100' : 'opacity-0'
            }`}
            onMouseDown={(event) => {
              if (event.target === inputRef.current) return
              event.preventDefault()
              inputRef.current?.focus()
            }}
          >
            <input
              ref={inputRef}
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              inputMode="numeric"
              className="num w-12 border-0 bg-transparent p-0 text-right text-[15px] text-ink-1 outline-none"
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onFocus={() => setIsEditing(true)}
              onBlur={() => {
                if (validValue !== null) setIsEditing(false)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && validValue !== null) {
                  event.preventDefault()
                  event.currentTarget.blur()
                  return
                }
                onKeyDown(event)
              }}
            />
            <span className="flex-none text-[12px] text-ink-3">秒</span>
          </div>
        </div>
        <button
          type="button"
          aria-label="增加 30 秒"
          title="增加 30 秒"
          className={`${stepButton} border-l border-l-line`}
          disabled={increaseDisabled}
          onClick={() => applyStep(increaseValue)}
        >
          +
        </button>
      </div>
      <ExecutionTimeoutHelp />
    </div>
  )
}
