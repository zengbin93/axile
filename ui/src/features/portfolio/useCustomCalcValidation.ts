import { useMemo, useState } from 'react'
import type { PythonValidationState } from '@/components/ui/PythonFunctionEditor'
import type { SelectOption } from '@/components/ui/Select'
import { channelLabel } from '@/features/dashboard/display'
import { validateCustomCalc } from '@/lib/api/portfolios'
import { useDomainStore } from '@/stores/domain'
import type { ValidateCustomCalcResult } from '@/types/api'

export interface CustomCalcValidation {
  validating: boolean
  /** 原始校验结果（含 target 权重），供结果区渲染。 */
  result: ValidateCustomCalcResult | null
  /** 编辑器直接消费的状态视图（错误行定位 / traceback）。 */
  editorResult: PythonValidationState | null
  /** 代码在最后一次试跑后又改过：结果保留展示但整体降级，不冒充新结论。 */
  stale: boolean
  accountId: number | null
  setAccountId: (id: number | null) => void
  contextOptions: SelectOption<number | null>[]
  canRun: boolean
  run: () => Promise<ValidateCustomCalcResult | null>
}

/**
 * 「试跑目标计算函数」状态机：代码 + 试跑上下文 → 校验结果。
 * 改代码不清空旧结果，仅降级 stale（清空收放会让打字中的代码跳）。
 * 工作台编辑页与初始化向导（console 布局）共用这一份逻辑。
 */
export function useCustomCalcValidation(code: string): CustomCalcValidation {
  const [validating, setValidating] = useState(false)
  const [result, setResult] = useState<ValidateCustomCalcResult | null>(null)
  const [ranCode, setRanCode] = useState<string | null>(null)
  const [accountId, setAccountId] = useState<number | null>(null)
  const accounts = useDomainStore((state) => state.accounts) ?? []
  const stale = result != null && ranCode !== code
  // 面板自动展开监听对象身份；只有真正的新试跑结果才生成新视图，避免手动收起后被普通重渲染顶开。
  const editorResult = useMemo<PythonValidationState | null>(
    () =>
      result && {
        valid: result.valid,
        errorLine: result.error_line,
        errorType: result.error_type,
        errorMessage: result.error_message,
        traceback: result.traceback,
      },
    [result],
  )

  const run = async () => {
    if (!code.trim() || validating) return null
    setValidating(true)
    let nextResult: ValidateCustomCalcResult
    try {
      nextResult = await validateCustomCalc({ custom_calc_py_code: code, account_id: accountId })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      nextResult = {
        valid: false,
        target: null,
        error: message,
        traceback: null,
        error_line: null,
        error_offset: null,
        error_type: null,
        error_message: message,
      }
    }
    setResult(nextResult)
    setRanCode(code)
    setValidating(false)
    return nextResult
  }

  // 选项自带说明：样例 = 安全沙箱（假数据、不连渠道）；账户 = 真实数据 + 真实副作用风险。
  // 控件只说「样例上下文」会把这两级语义全吞掉。
  const contextOptions: SelectOption<number | null>[] = [
    { value: null, label: '样例数据', description: '固定样例资产，价格恒为 100，不连接真实渠道' },
    ...accounts.map((account) => ({
      value: account.account_id,
      label: account.name,
      description: '真实持仓与行情 · 主动交易会产生真实委托',
      hint: channelLabel(account.trade_channel, account.market),
    })),
  ]

  return {
    validating,
    result,
    editorResult,
    stale,
    accountId,
    setAccountId,
    contextOptions,
    canRun: Boolean(code.trim()) && !validating,
    run,
  }
}
