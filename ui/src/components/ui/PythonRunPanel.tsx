import { useEffect, useState, type ReactNode } from 'react'
import { Check, ChevronDown, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'
import {
  PYTHON_RUN_STYLE,
  PythonRunResultBody,
  pythonRunStatus,
  type PythonValidationState,
} from '@/components/ui/PythonFunctionEditor'

/**
 * 试跑结果 split pane（工作台左栏位）：标题栏常驻（折叠 chevron + 状态句同槽换字），
 * 内容区 grid-fr 两态收放——收放即全部连续性，标题栏与保存区位置不跳。
 * 新结果自动展开；用户手动收起后保持到下一次新结果（result 引用变化才再展开）。
 * 卡片恒吃满父容器给的余高，权重清单长时内容区内滚。
 */
export function PythonRunPanel({
  running,
  result,
  stale,
  resultContent,
  className,
}: {
  running: boolean
  result: PythonValidationState | null
  /** 代码在最后一次试跑后又改过：结果保留展示但整体降级，不冒充新结论。 */
  stale: boolean
  resultContent?: ReactNode
  /** 尺寸由父容器决定（如 `flex-1 min-h-[140px]`），本组件只管内部结构。 */
  className?: string
}) {
  const [open, setOpen] = useState(false)

  // 新结果自动展开；result 引用不变（未再试跑）时不打扰用户的手动收起。
  useEffect(() => {
    if (result) setOpen(true)
  }, [result])

  const status = pythonRunStatus(running, result, stale)
  const style = PYTHON_RUN_STYLE[status]

  return (
    <div className={`flex min-h-0 flex-col overflow-hidden rounded-[8px] border border-line bg-surface ${className ?? ''}`}>
      <button
        type="button"
        className="flex w-full flex-none cursor-pointer items-center gap-2 px-3.5 py-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <ChevronDown
          size={14}
          aria-hidden
          className={`flex-none text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${open ? '' : '-rotate-90'}`}
        />
        <span className="flex h-3.5 w-3.5 flex-none items-center justify-center">
          {status === 'pass' && <Check size={14} className="text-accent" />}
          {status === 'fail' && <TriangleAlert size={14} className="text-warn" />}
        </span>
        <InkRewrite text={style.body} tone="label" textClassName={style.text} />
      </button>
      <div
        className={`grid min-h-0 flex-1 transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="h-full overflow-y-auto border-t border-line px-3.5 py-3">
            {result ? (
              <PythonRunResultBody result={result} stale={stale} resultContent={resultContent} />
            ) : (
              <p className="text-[13.5px] text-ink-3">试跑后将在这里显示返回权重或错误。</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
