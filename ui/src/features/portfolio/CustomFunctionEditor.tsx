import { useEffect, useRef } from 'react'
import { Check } from 'lucide-react'
import { PythonFunctionEditor } from '@/components/ui/PythonFunctionEditor'
import { WeightBars } from '@/components/viz/WeightBars'
import { Select } from '@/components/ui/Select'
import { useCustomCalcValidation } from '@/features/portfolio/useCustomCalcValidation'

export interface VerifiedState {
  ok: boolean
}

interface CustomFunctionEditorProps {
  code: string
  onChange: (code: string) => void
  onVerifiedChange?: (value: VerifiedState | null) => void
  /** 吃满父容器高度（工作台布局）；缺省自动高度封顶 40vh（向导等表单场景）。 */
  fill?: boolean
}

/**
 * 编辑并试跑唯一的组合目标计算函数（console 布局：工具条 + 内嵌结果带）。
 * 状态机在 :func:`useCustomCalcValidation`；工作台形态由页面直接组合
 * PythonFunctionEditor + 该 hook，把控件摆进左栏。
 */
export function CustomFunctionEditor({ code, onChange, onVerifiedChange, fill = false }: CustomFunctionEditorProps) {
  const v = useCustomCalcValidation(code)
  const onVerifiedChangeRef = useRef(onVerifiedChange)

  useEffect(() => {
    onVerifiedChangeRef.current = onVerifiedChange
  }, [onVerifiedChange])
  useEffect(() => {
    onVerifiedChangeRef.current?.(v.result == null || v.stale ? null : { ok: v.result.valid })
  }, [v.result, v.stale])

  return (
    <PythonFunctionEditor
      code={code}
      onChange={onChange}
      running={v.validating}
      stale={v.stale}
      result={v.editorResult}
      onRun={() => void v.run()}
      docHref="/docs/custom-calc"
      fill={fill}
      height={fill ? undefined : 'auto'}
      minHeight={fill ? undefined : '240px'}
      maxHeight={fill ? undefined : '40vh'}
      controls={
        <Select<number | null>
          ariaLabel="试跑上下文"
          value={v.accountId}
          onChange={v.setAccountId}
          options={v.contextOptions}
        />
      }
      resultContent={v.result?.valid && v.result.target ? <WeightResult target={v.result.target} /> : null}
    />
  )
}

/** 试跑通过的返回权重清单；结果带 / panel 已提供分层，内容不套卡片壳。 */
export function WeightResult({ target }: { target: Record<string, number> }) {
  const entries = Object.entries(target).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0)
  return (
    <div>
      <div className="mb-2.5 flex items-center justify-between text-[14px]">
        <span className="flex items-center gap-1.5 font-[550] text-accent"><Check size={14} /> 返回权重</span>
        <span className="text-ink-3">合计 <span className="num text-ink-2">{total.toFixed(2)}</span></span>
      </div>
      {entries.length === 0 ? (
        <p className="text-[14px] text-ink-3">返回空仓 {'{}'}</p>
      ) : (
        <WeightBars weights={entries} format="raw" />
      )}
    </div>
  )
}
