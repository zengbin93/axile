import { useEffect, useRef, useState, type ReactNode } from 'react'
import { python } from '@codemirror/lang-python'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { Check, Clipboard, Play, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', fontSize: '14px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none' },
  '.cm-content': { fontFamily: 'var(--font-mono)' },
})

export interface PythonValidationState {
  valid: boolean
  errorLine?: number | null
  errorType?: string | null
  errorMessage?: string | null
  traceback?: string | null
}

/**
 * 代码 + 试跑 console：工具条（状态句/操作/试跑）钉在代码上方，结果区在工具条与
 * 代码之间 grid-fr 常挂收放，代码区自身封顶内滚——循环部件的位置与代码长度解耦。
 */
export function PythonFunctionEditor({
  code,
  onChange,
  running,
  result,
  onRun,
  controls,
  resultContent,
  docHref,
  height = '320px',
  minHeight,
  maxHeight,
  runLabel = '试跑',
  disabled = false,
  stale = false,
}: {
  code: string
  onChange: (code: string) => void
  running: boolean
  result: PythonValidationState | null
  onRun: () => void
  controls?: ReactNode
  resultContent?: ReactNode
  docHref?: string
  height?: string
  minHeight?: string
  maxHeight?: string
  runLabel?: string
  disabled?: boolean
  /** 代码在最后一次试跑后又改过：结果保留展示但整体降级为中性，不冒充新结论。 */
  stale?: boolean
}) {
  const cmRef = useRef<ReactCodeMirrorRef>(null)
  const hasCode = code.trim().length > 0
  const [dialogOpen, setDialogOpen] = useState(false)
  const closeRef = useRef<HTMLButtonElement>(null)
  const runTriggerRef = useRef<HTMLElement | null>(null)

  // 试跑结束即弹窗呈现结果：代码框保持全宽，结果不再挤在编辑器下方。
  useEffect(() => {
    if (result) setDialogOpen(true)
  }, [result])

  useEffect(() => {
    if (!dialogOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDialogOpen(false)
    }
    window.addEventListener('keydown', onKey)
    runTriggerRef.current = document.activeElement as HTMLElement | null
    closeRef.current?.focus({ preventScroll: true })
    return () => {
      window.removeEventListener('keydown', onKey)
      runTriggerRef.current?.focus?.({ preventScroll: true })
    }
  }, [dialogOpen])

  useEffect(() => {
    const view = cmRef.current?.view
    if (!view) return
    const diagnostics: Diagnostic[] = []
    let errorFrom: number | null = null
    if (result && !result.valid && result.errorLine != null) {
      const lineNo = Math.min(Math.max(result.errorLine, 1), view.state.doc.lines)
      const line = view.state.doc.line(lineNo)
      const message = [result.errorType, result.errorMessage].filter(Boolean).join(': ')
      diagnostics.push({ from: line.from, to: line.to, severity: 'error', message: message || '试跑未通过' })
      errorFrom = line.from
    }
    // 失败时把错误行滚进可视区，省掉在长代码里找 lint 红标。
    view.dispatch(
      setDiagnostics(view.state, diagnostics),
      errorFrom != null ? { effects: EditorView.scrollIntoView(errorFrom, { y: 'center' }) } : {},
    )
  }, [result])

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) onChange(text)
    } finally {
      cmRef.current?.view?.focus()
    }
  }

  const status = running ? 'running' : result == null ? 'idle' : stale ? 'stale' : result.valid ? 'pass' : 'fail'
  const style = {
    running: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '试跑中…' },
    idle: { rail: 'border-line', band: 'border-line bg-surface', text: 'text-ink-3', body: '尚未试跑' },
    stale: { rail: 'border-line', band: 'border-line bg-surface', text: 'text-ink-3', body: '代码已改 · 结果为上次试跑' },
    pass: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '试跑通过' },
    fail: { rail: 'border-warn', band: 'border-warn/30 bg-warn/10', text: 'text-warn', body: '未通过' },
  }[status]

  return (
    <div className="w-full">
      <div className={`overflow-hidden rounded-[8px] border-l-[3px] ${hasCode ? style.rail : 'border-line'}`}>
        {/* 工具条：状态句同槽换字；图标槽恒占 14px，出现/消失不推字。 */}
        <div className={`flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b px-3.5 py-2.5 ${style.band}`}>
          <span className="flex min-w-[130px] flex-1 items-center gap-1.5 text-[14px] font-[520]">
            <span className="flex h-3.5 w-3.5 flex-none items-center justify-center">
              {status === 'pass' && <Check size={14} className="text-accent" />}
              {status === 'fail' && <TriangleAlert size={14} className="text-warn" />}
            </span>
            <InkRewrite text={style.body} tone="label" textClassName={style.text} />
          </span>
          {hasCode && (
            <button className="inline-flex cursor-pointer items-center gap-1.5 text-[14px] text-accent disabled:cursor-default disabled:opacity-45" onClick={() => void paste()} disabled={disabled}>
              <Clipboard size={14} /> 粘贴
            </button>
          )}
          {docHref && <a className="text-[14px] text-accent" href={docHref} target="_blank" rel="noopener">开发文档 ↗</a>}
          {controls}
          <button className="inline-flex cursor-pointer items-center gap-1.5 rounded-[8px] border-0 bg-ink-1 px-4 py-1.5 text-[14.5px] font-[550] text-surface disabled:cursor-default disabled:opacity-45" onClick={onRun} disabled={running || disabled || !hasCode}>
            <Play size={14} /> {runLabel}
          </button>
        </div>

        {/* 结果呈现走弹窗（试跑结束自动弹出，见下）：代码框保持全宽全高，不被结果挤压。 */}

        <div className="relative bg-code-bg">
          <CodeMirror
            ref={cmRef}
            value={code}
            onChange={onChange}
            height={height}
            minHeight={minHeight}
            maxHeight={maxHeight}
            theme="none"
            extensions={[oneDark, editorTheme, python(), lintGutter(), EditorView.lineWrapping, EditorView.editable.of(!disabled)]}
            basicSetup={{ foldGutter: false, highlightActiveLine: false, highlightActiveLineGutter: false, autocompletion: false }}
          />
          {!hasCode && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2">
              <button className="pointer-events-auto inline-flex cursor-pointer items-center gap-2 rounded-[8px] border border-line bg-surface px-5 py-3 text-[15px] font-[550] text-ink-1 shadow-sm hover:border-ink-3" onClick={() => void paste()}>
                <Clipboard size={16} /> 从剪贴板粘贴代码
              </button>
              <span className="text-[13.5px] text-ink-3">或点此直接输入</span>
            </div>
          )}
        </div>
      </div>

      {/* 试跑结果弹窗：通过 → resultContent（返回权重）；未通过 → 错误摘要 + traceback。 */}
      <div
        className={`fixed inset-0 z-[35] bg-scrim transition-opacity duration-150 ${dialogOpen ? 'opacity-100' : 'pointer-events-none opacity-0'}`}
        onClick={() => setDialogOpen(false)}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="试跑结果"
        className={`fixed left-1/2 top-1/2 z-[36] w-[560px] max-w-[92vw] -translate-x-1/2 rounded-[18px] bg-surface shadow-[0_24px_60px_rgba(0,0,0,0.24)] transition-all duration-150 ${
          dialogOpen ? '-translate-y-1/2 opacity-100' : 'pointer-events-none -translate-y-[46%] opacity-0'
        }`}
      >
        {result && dialogOpen && (
          <>
            <div className={`flex items-center gap-2 px-[22px] pt-5 pb-1.5 text-[18px] font-[640] ${result.valid ? 'text-accent' : 'text-warn'}`}>
              {result.valid ? <Check size={17} /> : <TriangleAlert size={17} />}
              {result.valid ? '试跑通过' : '试跑未通过'}
            </div>
            <div className="max-h-[60vh] overflow-y-auto px-[22px] pb-[18px] text-[14.5px] leading-relaxed">
              {result.valid
                ? (resultContent ?? <p className="text-ink-2">函数执行成功。</p>)
                : (
                  <>
                    <p className="font-mono text-[13.5px] text-warn">
                      {[result.errorType, result.errorMessage].filter(Boolean).join(': ') || '执行出错'}
                    </p>
                    {result.traceback && (
                      <details className="mt-3 rounded-[8px] border border-line bg-code-bg px-4 py-3" open>
                        <summary className="cursor-pointer select-none text-[13.5px] text-ink-2">完整 traceback</summary>
                        <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-warn">{result.traceback}</pre>
                      </details>
                    )}
                  </>
                )}
            </div>
            <div className="flex justify-end border-t border-line px-5 py-3.5">
              <button
                ref={closeRef}
                className="inline-flex cursor-pointer items-center rounded-[9px] border-0 bg-ink-1 px-[18px] py-2 text-sm font-[550] text-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/55 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
                onClick={() => setDialogOpen(false)}
              >
                关闭
                <span aria-hidden className="text-[13px] leading-none opacity-55">⏎</span>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
