import type { ReactNode } from 'react'
import { Check, ChevronDown, Circle, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'
import {
  PYTHON_RUN_STYLE,
  pythonRunStatus,
  type PythonValidationState,
} from '@/components/ui/PythonFunctionEditor'

/** 工作台下半区的固定面板：业务返回值在左，代码问题在右。 */
export function PythonRunPanel({
  kind,
  open,
  onToggle,
  running,
  result,
  stale,
  resultContent,
  onRevealError,
  className,
}: {
  kind: 'result' | 'problems'
  open: boolean
  onToggle: () => void
  running: boolean
  result: PythonValidationState | null
  /** 代码在最后一次试跑后又改过：保留内容，但不冒充当前结论。 */
  stale: boolean
  resultContent?: ReactNode
  onRevealError?: (line: number) => void
  className?: string
}) {
  const status = pythonRunStatus(running, result, stale)
  const style = PYTHON_RUN_STYLE[status]
  const failed = result != null && !result.valid
  const title = kind === 'result' ? '试跑结果' : '问题'

  return (
    <section
      aria-label={title}
      className={`row-span-2 grid min-h-0 overflow-hidden bg-surface [grid-template-rows:subgrid] ${className ?? ''}`}
    >
      <header className={`flex h-9 flex-none items-stretch ${open ? 'border-b border-line' : ''}`}>
        <button
          type="button"
          aria-expanded={open}
          className={`flex cursor-pointer items-center gap-1.5 px-3.5 text-[12px] font-semibold tracking-wide text-ink-1 ${
            open ? 'border-b border-accent' : ''
          }`}
          onClick={onToggle}
        >
          <ChevronDown
            size={13}
            aria-hidden
            className={`text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${open ? '' : '-rotate-90'}`}
          />
          {title}
        </button>
        <span className="ml-auto flex items-center gap-1.5 px-3.5 text-[12.5px]">
          {status === 'pass' && kind === 'result' ? (
            <Check size={13} className="text-accent" />
          ) : failed && kind === 'problems' ? (
            <TriangleAlert size={13} className="text-warn" />
          ) : (
            <Circle size={7} className={running ? 'fill-accent text-accent' : 'fill-ink-3 text-ink-3'} />
          )}
          <InkRewrite
            text={failed ? (kind === 'problems' ? '1 个问题' : '无返回值') : style.body}
            tone="label"
            textClassName={failed && kind === 'problems' ? 'text-warn' : style.text}
          />
        </span>
      </header>

      <div
        inert={!open}
        className={`min-h-0 flex-1 overflow-auto px-3.5 py-3 [scrollbar-gutter:stable] ${stale ? 'opacity-55' : ''}`}
      >
        {kind === 'result' ? (
          result?.valid ? (
            (resultContent ?? <p className="text-[13.5px] text-ink-2">函数执行成功。</p>)
          ) : failed ? (
            <p className="text-[13.5px] text-ink-3">执行失败，没有返回结果。请查看问题面板。</p>
          ) : (
            <p className="text-[13.5px] text-ink-3">试跑后在这里显示目标权重。</p>
          )
        ) : failed ? (
          <div>
            <button
              type="button"
              className={`block w-full rounded-[6px] border-l-2 border-warn bg-warn/10 px-3 py-2 text-left ${
                result.errorLine != null ? 'cursor-pointer hover:bg-warn/15' : 'cursor-default'
              }`}
              onClick={() => result.errorLine != null && onRevealError?.(result.errorLine)}
            >
              <span className="font-mono text-[13px] leading-5 text-warn">
                {[result.errorType, result.errorMessage].filter(Boolean).join(': ') || '执行出错'}
              </span>
              {result.errorLine != null && <span className="ml-2 text-[12px] text-ink-3">第 {result.errorLine} 行</span>}
            </button>
            {result.traceback && (
              <details className="mt-2.5 rounded-[8px] border border-line bg-code-bg px-3.5 py-2.5">
                <summary className="cursor-pointer select-none text-[13px] text-ink-2">完整 traceback</summary>
                <pre className="mt-2 overflow-auto whitespace-pre-wrap font-mono text-[12.5px] leading-relaxed text-warn">
                  {result.traceback}
                </pre>
              </details>
            )}
          </div>
        ) : (
          <p className="text-[13.5px] text-ink-3">
            {result?.valid ? '未发现执行问题。' : '语法错误和运行异常会显示在这里。'}
          </p>
        )}
      </div>
    </section>
  )
}
