import { useEffect, useRef, useState } from 'react'
import { python } from '@codemirror/lang-python'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { Check, Clipboard, Play, TriangleAlert } from 'lucide-react'
import { Select } from '@/components/ui/Select'
import { validateCustomCalc } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import type { ValidateCustomCalcResult } from '@/types/api'

const cmEditorTheme = EditorView.theme({
  '&': { backgroundColor: 'transparent', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none' },
  '.cm-content': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' },
})

export interface VerifiedState {
  ok: boolean
}

interface CustomFunctionEditorProps {
  code: string
  onChange: (code: string) => void
  onVerifiedChange?: (value: VerifiedState | null) => void
}

/** 编辑并试跑唯一的组合目标计算函数。 */
export function CustomFunctionEditor({ code, onChange, onVerifiedChange }: CustomFunctionEditorProps) {
  const [validating, setValidating] = useState(false)
  const [result, setResult] = useState<ValidateCustomCalcResult | null>(null)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [validatedAccountId, setValidatedAccountId] = useState<number | null>(null)
  const accounts = useDomainStore((state) => state.accounts) ?? []
  const cmRef = useRef<ReactCodeMirrorRef>(null)
  const onVerifiedChangeRef = useRef(onVerifiedChange)
  const hasCode = code.trim().length > 0

  useEffect(() => {
    onVerifiedChangeRef.current = onVerifiedChange
  }, [onVerifiedChange])

  useEffect(() => {
    setResult(null)
  }, [code])

  useEffect(() => {
    onVerifiedChangeRef.current?.(result == null ? null : { ok: result.valid })
  }, [result])

  useEffect(() => {
    const view = cmRef.current?.view
    if (!view) return
    const diagnostics: Diagnostic[] = []
    if (result && !result.valid && result.error_line != null) {
      const lineNo = Math.min(Math.max(result.error_line, 1), view.state.doc.lines)
      const line = view.state.doc.line(lineNo)
      const message = [result.error_type, result.error_message].filter(Boolean).join(': ')
      diagnostics.push({ from: line.from, to: line.to, severity: 'error', message: message || '试跑未通过' })
    }
    view.dispatch(setDiagnostics(view.state, diagnostics))
  }, [result])

  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) onChange(text)
      else cmRef.current?.view?.focus()
    } catch {
      cmRef.current?.view?.focus()
    }
  }

  const runValidation = async () => {
    if (!hasCode || validating) return
    setValidating(true)
    setValidatedAccountId(accountId)
    try {
      setResult(await validateCustomCalc({ custom_calc_py_code: code, account_id: accountId }))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setResult({
        valid: false,
        target: null,
        error: message,
        traceback: null,
        error_line: null,
        error_offset: null,
        error_type: null,
        error_message: message,
      })
    } finally {
      setValidating(false)
    }
  }

  const sourceName =
    validatedAccountId == null
      ? '样例上下文'
      : (accounts.find((account) => account.account_id === validatedAccountId)?.name ?? `账户 #${validatedAccountId}`)
  const status = validating ? 'running' : result == null ? 'idle' : result.valid ? 'pass' : 'fail'
  const statusStyle = {
    running: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: '试跑中…' },
    idle: { rail: 'border-line', band: 'border-line bg-surface', text: 'text-ink-3', body: '尚未试跑' },
    pass: { rail: 'border-accent', band: 'border-accent/30 bg-accent-soft', text: 'text-accent', body: `已通过 · ${sourceName}` },
    fail: { rail: 'border-warn', band: 'border-warn/30 bg-warn/10', text: 'text-warn', body: '未通过' },
  }[status]

  return (
    <div className="max-w-[820px]">
      <div className="mb-2 flex items-center justify-end gap-4">
        {hasCode && (
          <button className="inline-flex cursor-pointer items-center gap-1.5 text-[13px] text-accent" onClick={pasteFromClipboard}>
            <Clipboard size={14} /> 粘贴
          </button>
        )}
        <a className="text-[13px] text-accent" href="/docs/custom-calc" target="_blank" rel="noopener">
          开发文档 ↗
        </a>
      </div>

      <div className={`overflow-hidden rounded-[8px] border-l-[3px] ${hasCode ? statusStyle.rail : 'border-line'}`}>
        <div className="relative bg-code-bg">
          <CodeMirror
            ref={cmRef}
            value={code}
            onChange={onChange}
            height="320px"
            theme="none"
            extensions={[oneDark, cmEditorTheme, python(), lintGutter(), EditorView.lineWrapping]}
            basicSetup={{
              foldGutter: false,
              highlightActiveLine: false,
              highlightActiveLineGutter: false,
              autocompletion: false,
            }}
          />
          {!hasCode && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2">
              <button
                className="pointer-events-auto inline-flex cursor-pointer items-center gap-2 rounded-[8px] border border-line bg-surface px-5 py-3 text-[14px] font-[550] text-ink-1 shadow-sm hover:border-ink-3"
                onClick={pasteFromClipboard}
              >
                <Clipboard size={16} /> 从剪贴板粘贴代码
              </button>
              <span className="text-[12.5px] text-ink-3">或点此直接输入</span>
            </div>
          )}
        </div>

        {hasCode && (
          <div className={`flex items-center gap-2.5 border-t px-3.5 py-2.5 ${statusStyle.band}`}>
            <span className={`flex min-w-0 flex-1 items-center gap-1.5 truncate text-[13px] font-[520] ${statusStyle.text}`}>
              {status === 'pass' && <Check size={14} />}
              {status === 'fail' && <TriangleAlert size={14} />}
              {statusStyle.body}
            </span>
            <Select<number | null>
              ariaLabel="试跑上下文"
              value={accountId}
              onChange={setAccountId}
              options={[
                { value: null, label: '样例上下文' },
                ...accounts.map((account) => ({ value: account.account_id, label: account.name })),
              ]}
            />
            <button
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-[8px] border-0 bg-ink-1 px-4 py-1.5 text-[13.5px] font-[550] text-surface disabled:opacity-45"
              onClick={runValidation}
              disabled={validating}
            >
              <Play size={14} /> 试跑
            </button>
          </div>
        )}
      </div>

      {result?.valid && result.target && <WeightResult target={result.target} />}
      {result && !result.valid && result.traceback && (
        <details className="mt-3 rounded-[8px] border border-line bg-code-bg px-4 py-3">
          <summary className="cursor-pointer select-none text-[12.5px] text-warn">完整 traceback</summary>
          <pre className="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-warn">
            {result.traceback}
          </pre>
        </details>
      )}
    </div>
  )
}

function WeightResult({ target }: { target: Record<string, number> }) {
  const entries = Object.entries(target).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0)

  return (
    <div className="mt-3 rounded-[8px] border border-line px-4 py-3.5">
      <div className="mb-2.5 flex items-center justify-between text-[13px]">
        <span className="flex items-center gap-1.5 font-[550] text-accent"><Check size={14} /> 返回权重</span>
        <span className="text-ink-3">合计 <span className="num text-ink-2">{total.toFixed(2)}</span></span>
      </div>
      {entries.length === 0 ? (
        <p className="text-[13px] text-ink-3">返回空仓 {'{}'}</p>
      ) : (
        <div className="grid gap-2 text-[13px]">
          {entries.map(([symbol, weight]) => (
            <div key={symbol} className="flex items-center gap-3 border-t border-line pt-2 first:border-0 first:pt-0">
              <span className="min-w-0 flex-1 truncate font-[520]">{symbol}</span>
              <span className="num text-ink-2">{weight.toFixed(4)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
