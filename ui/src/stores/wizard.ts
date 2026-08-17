import { create } from 'zustand'
import { defaultExecutionTimeoutForChannel } from '@/features/account/executionTimeout'
import { defaultAlgorithm, type AlgorithmRef } from '@/features/setup/algorithms'
import { getChannelDescriptor } from '@/stores/channels'
import type { GMConnectionMode } from '@/features/setup/gmConnection'
import type { TradeChannel } from '@/types/api'
import {
  defaultScheduleRule,
  type ScheduleRule,
  type TimerTab,
} from '@/features/setup/cron'

/** 组合流草稿。 */
export interface PortfolioDraft {
  name: string
  market: string
  mode: 'compose' | 'custom'
  /** 策略名 → 权重（%）。 */
  strategies: { name: string; weight: number }[]
  customCode: string
  /** 当前 tab 的「试跑」结论；改动配置即清空，供「下一步」软拦截读取。 */
  verified: { ok: boolean } | null
  /** 保存后回填的组合 ID。 */
  savedId: number | null
}

/** 账户流草稿。 */
export interface AccountDraft {
  name: string
  channel: TradeChannel
  /** 连接表单（渠道特定字段）。 */
  config: Record<string, unknown>
  /** GM 连接目标；仅供向导控制互斥字段，不提交给后端。 */
  gmConnectionMode: GMConnectionMode
  portfolioId: number | null
  /** 主交易算法引用（`{method, params}`）；由「怎么交易」步的算法编辑器产出。 */
  algorithm: AlgorithmRef
  longLeverage: string
  shortLeverage: string
  executionTimeout: string
  autoOn: boolean
  /** 快捷 tab 选中的预设 id（可多选，高级组合后较少使用）。 */
  presetIds: string[]
  supN: number
  supM: number
  rawCron: string
  /** 定时 UI：快捷 | 高级。 */
  timerTab: TimerTab
  /** 高级：时间规则；length≥2 时显示右栏组合列表。 */
  scheduleRules: ScheduleRule[]
  /** 高级当前编辑的规则 id。 */
  selectedRuleId: string
  /** 高级底部自定义表达式模式。 */
  customCronOn: boolean
}

interface WizardState {
  pf: PortfolioDraft
  acct: AccountDraft
  setPf: (patch: Partial<PortfolioDraft>) => void
  setAcct: (patch: Partial<AccountDraft>) => void
  resetPf: () => void
  resetAcct: () => void
}

/** 返回渠道对应的账户杠杆默认值。 */
export function defaultLeveragesForChannel(channel: TradeChannel) {
  const defaults = getChannelDescriptor(channel)?.defaults
  return {
    longLeverage: String(defaults?.long_leverage ?? 1),
    shortLeverage: String(defaults?.short_leverage ?? 1),
  }
}

const initialPf: PortfolioDraft = {
  name: '我的趋势组合',
  market: '加密货币',
  mode: 'compose',
  strategies: [],
  customCode: 'def calculate_portfolio(context):\n    # 返回 {品种: 目标权重}\n    return {"BTCUSDT": 0.5, "ETHUSDT": 0.5}',
  verified: null,
  savedId: null,
}

function initialTimerForCrypto() {
  const rule = defaultScheduleRule('crypto')
  return {
    presetIds: ['d1'] as string[],
    supN: 2,
    supM: 1,
    rawCron: '',
    timerTab: 'quick' as TimerTab,
    scheduleRules: [rule],
    selectedRuleId: rule.id,
    customCronOn: false,
  }
}

const initialAcct: AccountDraft = {
  name: '',
  channel: '',
  config: {},
  gmConnectionMode: 'terminal',
  portfolioId: null,
  algorithm: defaultAlgorithm('crypto', 'trade'),
  ...defaultLeveragesForChannel(''),
  executionTimeout: defaultExecutionTimeoutForChannel(''),
  autoOn: true,
  ...initialTimerForCrypto(),
}

/** 建号/建组合向导的跨步骤草稿。 */
export const useWizardStore = create<WizardState>((set) => ({
  pf: { ...initialPf },
  acct: { ...initialAcct },
  setPf: (patch) => set((s) => ({ pf: { ...s.pf, ...patch } })),
  setAcct: (patch) => set((s) => ({ acct: { ...s.acct, ...patch } })),
  resetPf: () => set({ pf: { ...initialPf, strategies: [] } }),
  resetAcct: () => set({ acct: { ...initialAcct, ...initialTimerForCrypto() } }),
}))
