import { useEffect, useImperativeHandle, useRef, type ReactNode, type Ref } from 'react'
import { python } from '@codemirror/lang-python'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { EditorView } from '@codemirror/view'
import { tags } from '@lezer/highlight'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { Check, Clipboard, Play, TriangleAlert } from 'lucide-react'
import { InkRewrite } from '@/components/ui/InkRewrite'

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'var(--color-code-bg)', color: 'var(--color-code-fg)', fontSize: '14px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'var(--color-code-bg)', color: 'var(--color-ink-3)', border: 'none' },
  '.cm-content': { fontFamily: 'var(--font-mono)' },
  '.cm-cursor': { borderLeftColor: 'var(--color-code-fg)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {
    backgroundColor: 'var(--color-code-selection) !important',
  },
})

const vscodeDarkHighlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.modifier, tags.controlKeyword, tags.operatorKeyword], color: 'var(--color-code-keyword)' },
  { tag: [tags.variableName, tags.propertyName], color: 'var(--color-code-name)' },
  { tag: [tags.function(tags.variableName), tags.definition(tags.variableName)], color: 'var(--color-code-function)' },
  { tag: [tags.string, tags.special(tags.string)], color: 'var(--color-code-string)' },
  { tag: [tags.number, tags.bool, tags.null], color: 'var(--color-code-number)' },
  { tag: [tags.className, tags.typeName, tags.namespace], color: 'var(--color-code-type)' },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: 'var(--color-code-comment)', fontStyle: 'italic' },
  { tag: [tags.operator, tags.punctuation], color: 'var(--color-code-fg)' },
])

export interface PythonValidationState {
  valid: boolean
  errorLine?: number | null
  errorType?: string | null
  errorMessage?: string | null
  traceback?: string | null
}

/** 暴露给外部控制的编辑器句柄（如「粘贴」按钮点击后把焦点还给代码区）。 */
export interface PythonEditorHandle {
  focus: () => void
  revealLine: (line: number) => void
}

export type PythonRunStatus = 'running' | 'idle' | 'stale' | 'pass' | 'fail'

/** 试跑状态归约：console 工具条与工作台结果 panel 共用同一份状态语义。 */
// oxlint-disable-next-line react/only-export-components -- 状态归约与编辑器组件同源，刻意合并
export function pythonRunStatus(
  running: boolean,
  result: PythonValidationState | null,
  stale: boolean,
): PythonRunStatus {
  return running ? 'running' : result == null ? 'idle' : stale ? 'stale' : result.valid ? 'pass' : 'fail'
}

/** 状态外观：成败不走红绿——通过/进行 = 蓝，未通过 = 琥珀，无事 = 中性。 */
// oxlint-disable-next-line react/only-export-components -- 状态外观表与状态归约同槽，刻意合并
export const PYTHON_RUN_STYLE: Record<PythonRunStatus, { rail: string; band: string; text: string; body: string }> = {
  running: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '试跑中…' },
  idle: { rail: 'border-line', band: 'border-line bg-surface', text: 'text-ink-3', body: '尚未试跑' },
  stale: { rail: 'border-line', band: 'border-line bg-surface', text: 'text-ink-3', body: '代码已改 · 结果为上次试跑' },
  pass: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '试跑通过' },
  fail: { rail: 'border-warn', band: 'border-warn/30 bg-warn/10', text: 'text-warn', body: '未通过' },
}

/** 结果正文（console 结果带与 PythonRunPanel 共用）：通过 → resultContent；未通过 → 错误摘要 + traceback。 */
export function PythonRunResultBody({
  result,
  stale,
  resultContent,
}: {
  result: PythonValidationState
  stale: boolean
  resultContent?: ReactNode
}) {
  return (
    <div className={stale ? 'opacity-55' : undefined}>
      {result.valid ? (
        (resultContent ?? <p className="text-[14px] text-ink-2">函数执行成功。</p>)
      ) : (
        <>
          <p className="font-mono text-[13.5px] text-warn">
            {[result.errorType, result.errorMessage].filter(Boolean).join(': ') || '执行出错'}
          </p>
          {result.traceback && (
            <details className="mt-2.5 rounded-[8px] border border-line bg-code-bg px-4 py-3">
              <summary className="cursor-pointer select-none text-[13.5px] text-ink-2">完整 traceback</summary>
              <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-warn">
                {result.traceback}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  )
}

/**
 * 代码 + 试跑 console，两种布局：
 *
 * - `console`（默认，表单/向导场景）：工具条（状态句/操作/试跑）钉在代码上方，
 *   结果区在工具条与代码之间 grid-fr 常挂收放，代码区按 height/min/max 自定高度。
 * - `workbench`（工作台编辑页）：纯代码区吃满父容器，无任何工具条——控制件与
 *   结果呈现全部外置（结果走 :func:`PythonRunPanel`，可摆进左栏做 split pane）。
 *
 * 两种布局都支持 Ctrl/Cmd+Enter 试跑；失败时错误行进 lint 并滚入可视区。
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
  fill = false,
  layout = 'console',
  ref,
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
  /** 吃满父容器高度（父链须给出确定高度）；console 布局缺省按 height/min/max 定高。 */
  fill?: boolean
  /** 布局形态：console = 表单内嵌（工具条 + 结果带）；workbench = 纯代码区。 */
  layout?: 'console' | 'workbench'
  ref?: Ref<PythonEditorHandle>
}) {
  const cmRef = useRef<ReactCodeMirrorRef>(null)
  const hasCode = code.trim().length > 0
  const onRunRef = useRef(onRun)
  onRunRef.current = onRun

  useImperativeHandle(
    ref,
    () => ({
      focus: () => cmRef.current?.view?.focus(),
      revealLine: (lineNo: number) => {
        const view = cmRef.current?.view
        if (!view) return
        const line = view.state.doc.line(Math.min(Math.max(lineNo, 1), view.state.doc.lines))
        view.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) })
        view.focus()
      },
    }),
    [],
  )

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

  const status = pythonRunStatus(running, result, stale)
  const style = PYTHON_RUN_STYLE[status]

  // Ctrl/Cmd+Enter 试跑（VSCode Run 的肌肉记忆）；onRun 内部自行判断 canRun。
  const runKeymap = EditorView.domEventHandlers({
    keydown: (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault()
        onRunRef.current()
        return true
      }
      return false
    },
  })
  const extensions = [
    editorTheme,
    syntaxHighlighting(vscodeDarkHighlight),
    python(),
    lintGutter(),
    EditorView.lineWrapping,
    EditorView.editable.of(!disabled),
    runKeymap,
  ]

  const codeBlock = (
    <div className={`relative bg-code-bg ${fill ? 'min-h-0 flex-1' : ''}`}>
      <CodeMirror
        ref={cmRef}
        className={
          fill
            ? 'h-full [&_.cm-editor]:h-full [&_.cm-editor]:!bg-code-bg [&_.cm-gutters]:!bg-code-bg [&_.cm-scroller]:h-full'
            : '[&_.cm-editor]:!bg-code-bg [&_.cm-gutters]:!bg-code-bg'
        }
        value={code}
        onChange={onChange}
        height={fill ? '100%' : height}
        minHeight={fill ? undefined : minHeight}
        maxHeight={fill ? undefined : maxHeight}
        theme="none"
        extensions={extensions}
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
  )

  if (layout === 'workbench') {
    // 工作台：纯代码区，吃满父容器；结果呈现由外部 PythonRunPanel 承担。
    return (
      <div className="flex h-full min-h-0 w-full flex-col">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{codeBlock}</div>
      </div>
    )
  }

  // console：表单/向导内嵌布局，工具条钉在代码上方，结果带内嵌收放。
  const resultOpen = result != null
  return (
    <div className={fill ? 'flex h-full min-h-0 w-full flex-col' : 'w-full'}>
      <div
        className={`overflow-hidden rounded-[8px] border-l-[3px] ${hasCode ? style.rail : 'border-line'} ${
          fill ? 'flex min-h-0 flex-1 flex-col' : ''
        }`}
      >
        {/* 工具条：状态句同槽换字；图标槽恒占 14px，出现/消失不推字。 */}
        <div className={`flex flex-none flex-wrap items-center gap-x-3.5 gap-y-2 border-b px-3.5 py-2.5 ${style.band}`}>
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

        {/* 结果区：工具条与代码之间 grid-fr 常挂收放（收放即全部连续性，不再叠 fade）；
            stale 时整体降级，旧结论不冒充新结论。权重清单长时区内自滚，不挤压代码区。 */}
        <div
          inert={!resultOpen}
          className={`flex-none grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${
            resultOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            {result && (
              <div className="max-h-[38vh] overflow-y-auto border-b border-line px-3.5 py-3">
                <PythonRunResultBody result={result} stale={stale} resultContent={resultContent} />
              </div>
            )}
          </div>
        </div>

        {codeBlock}
      </div>
    </div>
  )
}
