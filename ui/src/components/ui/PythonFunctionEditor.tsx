import { useEffect, useRef, type ReactNode } from 'react'
import { python } from '@codemirror/lang-python'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { Check, Clipboard, Play, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none' },
  '.cm-content': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' },
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

  // 结果面板常挂、grid-fr 收放：stale 时保持展开（降透明度），打字时代码不跳。
  const panelOpen = result != null && (result.valid ? resultContent != null : true)

  return (
    <div className="w-full">
      <div className={`overflow-hidden rounded-[8px] border-l-[3px] ${hasCode ? style.rail : 'border-line'}`}>
        {/* 工具条：状态句同槽换字；图标槽恒占 14px，出现/消失不推字。 */}
        <div className={`flex flex-wrap items-center gap-x-3.5 gap-y-2 border-b px-3.5 py-2.5 ${style.band}`}>
          <span className="flex min-w-[130px] flex-1 items-center gap-1.5 text-[13px] font-[520]">
            <span className="flex h-3.5 w-3.5 flex-none items-center justify-center">
              {status === 'pass' && <Check size={14} className="text-accent" />}
              {status === 'fail' && <TriangleAlert size={14} className="text-warn" />}
            </span>
            <InkRewrite text={style.body} tone="label" textClassName={style.text} />
          </span>
          {hasCode && (
            <button className="inline-flex cursor-pointer items-center gap-1.5 text-[13px] text-accent disabled:cursor-default disabled:opacity-45" onClick={() => void paste()} disabled={disabled}>
              <Clipboard size={14} /> 粘贴
            </button>
          )}
          {docHref && <a className="text-[13px] text-accent" href={docHref} target="_blank" rel="noopener">开发文档 ↗</a>}
          {controls}
          <button className="inline-flex cursor-pointer items-center gap-1.5 rounded-[8px] border-0 bg-ink-1 px-4 py-1.5 text-[13.5px] font-[550] text-surface disabled:cursor-default disabled:opacity-45" onClick={onRun} disabled={running || disabled || !hasCode}>
            <Play size={14} /> {runLabel}
          </button>
        </div>

        {/* 结果区：权重 / 错误摘要 + traceback。 */}
        <div className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${panelOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
          <div className="min-h-0 overflow-hidden" inert={!panelOpen}>
            <div className={`border-b border-line bg-surface px-3.5 py-3 transition-opacity duration-200 motion-reduce:transition-none ${stale ? 'opacity-55' : ''}`}>
              {result != null && !result.valid && (
                <p className="text-[13px] text-warn">
                  {[result.errorType, result.errorMessage].filter(Boolean).join(': ') || '试跑未通过'}
                </p>
              )}
              {resultContent}
              {result != null && !result.valid && result.traceback && (
                <details className="mt-2 rounded-[8px] border border-line bg-code-bg px-4 py-3">
                  <summary className="cursor-pointer select-none text-[12.5px] text-warn">完整 traceback</summary>
                  <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-warn">{result.traceback}</pre>
                </details>
              )}
            </div>
          </div>
        </div>

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
              <button className="pointer-events-auto inline-flex cursor-pointer items-center gap-2 rounded-[8px] border border-line bg-surface px-5 py-3 text-[14px] font-[550] text-ink-1 shadow-sm hover:border-ink-3" onClick={() => void paste()}>
                <Clipboard size={16} /> 从剪贴板粘贴代码
              </button>
              <span className="text-[12.5px] text-ink-3">或点此直接输入</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
