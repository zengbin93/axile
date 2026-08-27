import type { ReactElement } from 'react'

/** 选项组的单个选项：值与显示文案分离。 */
export interface ChoiceOption<T extends string> {
  value: T
  label: string
}

/**
 * 单选选项组（受控），语义为 radiogroup。

 * 与 {@link Segmented} 的区别在语义而非样式：分段控件用于「切换视图」，
 * 每个选项是同一内容的平行视图；本组件用于「选取一个取值」——选项是相互
 * 独立的候选项，选中项成为表单的一个属性。因此渲染为一排相互独立的描边
 * 药丸，而非共享凹槽的滑块，避免读起来像标签页导航。
 *
 * @typeParam T - 选项值的字面量联合类型。
 */
export function ChoiceGroup<T extends string>({
  value,
  options,
  onChange,
  className = '',
}: {
  value: T
  options: ChoiceOption<T>[]
  onChange: (value: T) => void
  className?: string
}): ReactElement {
  return (
    <div role="radiogroup" className={`flex flex-wrap gap-2 ${className}`}>
      {options.map((o) => {
        const selected = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`cursor-pointer rounded-[9px] border px-4 py-2 text-[15px] transition-colors ${
              selected
                ? 'border-accent bg-accent-soft font-semibold text-ink-1'
                : 'border-ink-3/30 text-ink-2 hover:border-ink-3/60 hover:text-ink-1'
            }`}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
