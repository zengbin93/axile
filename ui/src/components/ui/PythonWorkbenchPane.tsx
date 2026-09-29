import { useEffect, useRef, useState, type Ref } from 'react'
import { PythonFunctionEditor, PythonRunResultBody, type PythonEditorHandle, type PythonProblem, type PythonValidationState } from '@/components/ui/PythonFunctionEditor'
import { PythonRunPanel } from '@/components/ui/PythonRunPanel'

const DEFAULT_SPLIT = 0.35

function initialSplit(storageKey: string) {
  if (typeof window === 'undefined') return DEFAULT_SPLIT
  const stored = Number(window.localStorage.getItem(storageKey))
  return Number.isFinite(stored) && stored >= 0.2 && stored <= 0.8 ? stored : DEFAULT_SPLIT
}

/** 工作台的代码区、静态问题与试跑结果；业务页提供代码、执行行为和状态栏槽位。 */
export function PythonWorkbenchPane({
  code, onChange, running, stale, result, onRun, editorRef, statusTarget, storageKey,
  title, docHref, onResizeChange,
}: {
  code: string
  onChange: (code: string) => void
  running: boolean
  stale: boolean
  result: PythonValidationState | null
  onRun: () => void
  editorRef: Ref<PythonEditorHandle>
  statusTarget: HTMLElement | null
  storageKey: string
  title: string
  docHref?: string
  onResizeChange?: (resizing: boolean) => void
}) {
  const [problemsOpen, setProblemsOpen] = useState(false)
  const [problems, setProblems] = useState<PythonProblem[]>([])
  const [split, setSplit] = useState(() => initialSplit(storageKey))
  const [resizing, setResizing] = useState(false)
  const [header, setHeader] = useState<HTMLDivElement | null>(null)
  const paneRef = useRef<HTMLDivElement>(null)
  const internalEditorRef = useRef<PythonEditorHandle>(null)

  useEffect(() => {
    if (result) setProblemsOpen(!result.valid)
  }, [result])

  const setResizingState = (value: boolean) => {
    setResizing(value)
    onResizeChange?.(value)
  }
  const splitAt = (clientY: number) => {
    const bounds = paneRef.current?.getBoundingClientRect()
    if (!bounds) return split
    const available = bounds.height - 5 - 36
    if (available <= 0) return split
    const minShare = Math.min(0.45, 120 / available)
    return Math.min(Math.max((bounds.bottom - clientY - 41) / available, minShare), 1 - minShare)
  }
  const persistSplit = (value: number) => {
    setSplit(value)
    window.localStorage.setItem(storageKey, String(value))
  }
  const rows = problemsOpen
    ? `minmax(0, ${1 - split}fr) 5px 36px minmax(0, ${split}fr)`
    : 'minmax(0, 1fr) 0px 36px minmax(0, 0fr)'
  const staticProblems = problems.filter((problem) => problem.source === 'ty')

  return (
    <div ref={paneRef} className={`grid min-h-0 transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${resizing ? '!transition-none' : ''}`} style={{ gridTemplateRows: rows }}>
      <div className="flex min-h-[420px] min-w-0 flex-col bg-code-bg md:min-h-0">
        <div ref={setHeader} className="h-8 flex-none" />
        <PythonFunctionEditor
          ref={(handle) => {
            internalEditorRef.current = handle
            if (typeof editorRef === 'function') editorRef(handle)
            else if (editorRef) editorRef.current = handle
          }}
          headerTarget={header}
          statusTarget={statusTarget}
          onProblems={setProblems}
          layout="workbench"
          fill
          code={code}
          onChange={onChange}
          running={running}
          stale={stale}
          result={result}
          onRun={onRun}
          workbenchTitle={title}
          docHref={docHref}
        />
      </div>
      <div
        role="separator"
        aria-label="调整代码与问题的高度"
        aria-orientation="horizontal"
        aria-valuemin={20}
        aria-valuemax={80}
        aria-valuenow={Math.round(split * 100)}
        tabIndex={problemsOpen ? 0 : -1}
        inert={!problemsOpen}
        title="拖动分配代码与问题的高度 · 双击平均分配"
        className={`group relative z-10 cursor-row-resize touch-none outline-none ${problemsOpen ? 'block' : 'invisible'}`}
        onDoubleClick={() => persistSplit(DEFAULT_SPLIT)}
        onPointerDown={(event) => {
          if (!problemsOpen) return
          event.preventDefault()
          event.currentTarget.setPointerCapture(event.pointerId)
          setResizingState(true)
          setSplit(splitAt(event.clientY))
        }}
        onPointerMove={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) setSplit(splitAt(event.clientY))
        }}
        onPointerUp={(event) => {
          const next = splitAt(event.clientY)
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
          persistSplit(next)
          setResizingState(false)
        }}
        onPointerCancel={() => setResizingState(false)}
        onKeyDown={(event) => {
          let next = split
          if (event.key === 'ArrowUp') next += 0.05
          else if (event.key === 'ArrowDown') next -= 0.05
          else if (event.key === 'Home') next = 0.2
          else if (event.key === 'End') next = 0.8
          else return
          event.preventDefault()
          persistSplit(Math.min(Math.max(next, 0.2), 0.8))
        }}
      >
        <span className="absolute inset-x-0 top-1/2 h-px bg-line transition-colors duration-130 group-hover:bg-accent group-focus:bg-accent" />
      </div>
      <PythonRunPanel
        kind="problems"
        title="代码问题 / 试跑"
        statusOverride={<span className="ml-auto self-center px-3 text-[12px] text-ink-3">{staticProblems.length} 个静态问题</span>}
        contentOverride={(
          <div className="space-y-3">
            <p className="text-[12px] text-ink-3">代码问题 · ty</p>
            {staticProblems.map((problem, index) => (
              <button key={`${index}-${problem.line}`} type="button" className="block w-full border-l-2 border-warn px-3 py-2 text-left text-[13px] text-warn" onClick={() => internalEditorRef.current?.revealLine(problem.line)}>
                第 {problem.line} 行 · {problem.message}
              </button>
            ))}
            {staticProblems.length === 0 && <p className="text-[13px] text-ink-3">暂无静态诊断。</p>}
            <p className="border-t border-line pt-3 text-[12px] text-ink-3">试跑结果{stale ? ' · 代码已修改，以下为旧结果' : ''}</p>
            {!stale && result?.errorLine != null && <button type="button" className="text-[12px] text-accent" onClick={() => internalEditorRef.current?.revealLine(result.errorLine!)}>定位到第 {result.errorLine} 行</button>}
            {result ? <PythonRunResultBody result={result} stale={stale} /> : <p className="text-[13px] text-ink-3">尚未试跑</p>}
          </div>
        )}
        open={problemsOpen}
        onToggle={() => setProblemsOpen((open) => !open)}
        className="border-t border-line"
        running={running}
        result={result}
        stale={false}
        onRevealError={(line) => internalEditorRef.current?.revealLine(line)}
      />
    </div>
  )
}
