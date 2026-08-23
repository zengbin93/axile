import { useEffect, useRef, useState } from 'react'
import { Check } from 'lucide-react'
import { PythonFunctionEditor } from '@/components/ui/PythonFunctionEditor'
import { Select } from '@/components/ui/Select'
import { validateCustomCalc } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import type { ValidateCustomCalcResult } from '@/types/api'

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
  const accounts = useDomainStore((state) => state.accounts) ?? []
  const onVerifiedChangeRef = useRef(onVerifiedChange)

  useEffect(() => {
    onVerifiedChangeRef.current = onVerifiedChange
  }, [onVerifiedChange])
  useEffect(() => {
    setResult(null)
  }, [code])
  useEffect(() => {
    onVerifiedChangeRef.current?.(result == null ? null : { ok: result.valid })
  }, [result])

  const runValidation = async () => {
    if (!code.trim() || validating) return
    setValidating(true)
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

  return (
    <PythonFunctionEditor
      code={code}
      onChange={onChange}
      running={validating}
      result={result && {
        valid: result.valid,
        errorLine: result.error_line,
        errorType: result.error_type,
        errorMessage: result.error_message,
        traceback: result.traceback,
      }}
      onRun={() => void runValidation()}
      docHref="/docs/custom-calc"
      controls={
        <Select<number | null>
          ariaLabel="试跑上下文"
          value={accountId}
          onChange={setAccountId}
          options={[
            { value: null, label: '样例上下文' },
            ...accounts.map((account) => ({ value: account.account_id, label: account.name })),
          ]}
        />
      }
      resultContent={result?.valid && result.target ? <WeightResult target={result.target} /> : null}
    />
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
