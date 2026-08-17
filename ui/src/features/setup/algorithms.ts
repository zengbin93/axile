/**
 * 交易意图 → 下单算法解析，以及算法槽位（主交易 / 清仓）的默认与种子参数。
 *
 * 后端算法是注册表（`GET /api/v1/algorithms` 供清单），account 只存 `{method, params}`
 * 引用。意图三档是 SINGLE-MAKER 的「结果导向」诠释；其余内置算法有各自专属编辑器，
 * 切换算法时用 `seedParams` 播下合法默认参数。
 */
import type { Market } from '@/features/setup/cron'
import type { AlgorithmInfo, AlgorithmRef, AlgorithmSlot } from '@/types/api'

export type { AlgorithmRef } from '@/types/api'

export type Intent = 'save' | 'fill' | 'balance'

/** 意图文案随市场变（挂单在不同市场省的东西不同）。 */
export const INTENT_COPY: Record<Market, Record<Intent, { title: string; desc: string; note: string; warn?: boolean }>> = {
  crypto: {
    save: { title: '省成本', desc: '只挂单 + 追单，走 maker 低费率、不吃点差', note: '成本最低，但可能填不满', warn: true },
    fill: { title: '保成交', desc: '立即吃单', note: '付点差 + taker 费率，单次必成交' },
    balance: { title: '平衡（推荐）', desc: '挂单为主，超时兜底吃单', note: '多数走低成本档，最终必成交' },
  },
  ctp: {
    save: { title: '省成本', desc: '只挂单 + 追单，省点差/冲击', note: '手续费固定不省，可能填不满', warn: true },
    fill: { title: '保成交', desc: '立即吃单', note: '付点差，单次必成交' },
    balance: { title: '平衡（推荐）', desc: '挂单为主，超时兜底吃单', note: '多数省点差，最终必成交' },
  },
  ashare: {
    save: { title: '省成本', desc: '只挂限价单 + 追单，省点差/冲击', note: '费率与挂单无关，可能填不满', warn: true },
    fill: { title: '保成交', desc: '立即市价成交', note: '付点差/冲击，单次必成交' },
    balance: { title: '平衡（推荐）', desc: '限价为主，超时兜底市价', note: '多数省点差，最终必成交' },
  },
}

/** 由意图 + 市场解析出下单算法引用。 */
export function resolveAlgorithm(intent: Intent, market: Market): AlgorithmRef {
  const method = market === 'ctp' ? 'TARGET-POS-TASK' : 'SINGLE-MAKER'
  const base: Record<string, unknown> = {
    price_strategy: 'PASSIVE',
    max_wait_seconds: 60,
    chase_enabled: true,
    chase_ticks: 1,
    max_chase_count: 5,
    chase_interval: 5,
  }
  if (intent === 'save') {
    // 省成本：尽量挂单、多次追单、不主动吃单。取后端合法上限——最长等待 3600s、
    // 追单 50 次（50×5=250s ≤ 600s 上限），而非非法的 0 / 99。
    return { method, params: { ...base, price_strategy: 'PASSIVE', chase_enabled: true, max_wait_seconds: 3600, max_chase_count: 50 } }
  }
  if (intent === 'fill') {
    return { method, params: { ...base, price_strategy: 'ACTIVE', chase_enabled: false, max_wait_seconds: 30 } }
  }
  return { method, params: { ...base, price_strategy: 'PASSIVE', chase_enabled: true, max_wait_seconds: 60 } }
}

/**
 * 校验算法参数是否满足后端约束，镜像 `BaseAlgorithmParams` / `ChaseParamsMixin`。
 *
 * 只校验存在且相关的键（max_wait_seconds / 追单族），其余键忽略。返回首个违规
 * 文案；全部合法返回 `null`。用于在提交前拦下非法 params，避免重蹈「参数被后端
 * 吞成 dict、执行到算法内部才炸」的覆辙。
 */
export function validateAlgorithmParams(params: Record<string, unknown>): string | null {
  const num = (k: string): number | undefined => (typeof params[k] === 'number' ? (params[k] as number) : undefined)

  const wait = num('max_wait_seconds')
  if (wait !== undefined && (!Number.isInteger(wait) || wait < 1 || wait > 3600)) {
    return `max_wait_seconds 需为 1–3600 的整数，当前 ${wait}`
  }

  // 切片类算法的数值参数：镜像各自 params 模型与编辑器 NumRow 的边界，
  // 与服务端校验同口径，避免「超范围」标红却仍能保存。
  const totalDuration = num('total_duration')
  if (totalDuration !== undefined && (!Number.isInteger(totalDuration) || totalDuration < 1 || totalDuration > 86400)) {
    return `total_duration 需为 1–86400 的整数，当前 ${totalDuration}`
  }
  const slices = num('slices')
  if (slices !== undefined && (!Number.isInteger(slices) || slices < 1 || slices > 1000)) {
    return `slices 需为 1–1000 的整数，当前 ${slices}`
  }
  const participation = num('participation_rate')
  if (participation !== undefined && (participation < 0.0001 || participation > 1)) {
    return `participation_rate 需在 0.0001–1，当前 ${participation}`
  }
  const intervalSeconds = num('interval_seconds')
  if (intervalSeconds !== undefined && intervalSeconds < 0.1) {
    return `interval_seconds 需 ≥ 0.1s，当前 ${intervalSeconds}`
  }
  const maxDuration = num('max_duration')
  if (maxDuration !== undefined && (!Number.isInteger(maxDuration) || maxDuration < 1 || maxDuration > 86400)) {
    return `max_duration 需为 1–86400 的整数，当前 ${maxDuration}`
  }

  if (params.chase_enabled === true) {
    const ticks = num('chase_ticks')
    const count = num('max_chase_count')
    const interval = num('chase_interval')
    if (ticks !== undefined && (ticks < 1 || ticks > 100)) return `启用追单时 chase_ticks 需在 1–100，当前 ${ticks}`
    if (count !== undefined && (count < 1 || count > 50)) return `启用追单时 max_chase_count 需在 1–50，当前 ${count}`
    if (interval !== undefined && (interval < 0.1 || interval > 300)) return `启用追单时 chase_interval 需在 0.1–300s，当前 ${interval}`
    if (count !== undefined && interval !== undefined && count * interval > 600) {
      return `追单总时长（max_chase_count×chase_interval=${count * interval}s）不应超过 600s`
    }
    if (interval !== undefined && count !== undefined && interval < 1 && count > 10) {
      return `追单间隔过短（<1s）且次数过多（>10），可能触发限频`
    }
  }
  return null
}

/** 清仓算法（目标清空时用）。 */
export function emptyAlgorithm(market: Market): AlgorithmRef {
  if (market === 'ctp') return { method: 'TARGET-POS-TASK', params: { price_strategy: 'ACTIVE', offset_priority: '昨今' } }
  return { method: 'SINGLE-MAKER', params: { price_strategy: 'ACTIVE' } }
}

/** 各算法的简明中文标签（选择器与徽标用）。 */
export const ALGO_LABEL: Record<string, string> = {
  'SINGLE-MAKER': '挂单追单',
  TWAP: '时间切片（TWAP）',
  POV: '成交量跟单（POV）',
  'TARGET-POS-TASK': '目标持仓',
  CTP_OPTION_EXERCISE: '期权行权',
}

let runtimeAlgorithmLabels: Record<string, string> = {}

/** 更新后端算法目录中的运行时展示名。 */
export function registerAlgorithmLabels(algorithms: AlgorithmInfo[]): void {
  runtimeAlgorithmLabels = Object.fromEntries(algorithms.map((algorithm) => [algorithm.name, algorithm.label]))
}

/** 返回某算法的展示标签；未知算法回退为其 method 原名。 */
export function algoLabel(method: string): string {
  return runtimeAlgorithmLabels[method] || ALGO_LABEL[method] || method
}

/** 槽位 + 市场的默认算法引用（含默认参数）。 */
export function defaultAlgorithm(market: Market, slot: AlgorithmSlot): AlgorithmRef {
  return slot === 'empty' ? emptyAlgorithm(market) : resolveAlgorithm('balance', market)
}

/**
 * 用户从选择器切换到某算法时播下的合法默认参数.
 *
 * 只包含各算法参数模型里真实存在的字段，避免生成会被后端拒绝或忽略的键。
 */
export function seedParams(method: string, market: Market): Record<string, unknown> {
  switch (method) {
    case 'SINGLE-MAKER':
      return resolveAlgorithm('balance', market).params
    case 'TWAP':
      return { total_duration: 300, slices: 10, price_strategy: 'PASSIVE' }
    case 'POV':
      return { participation_rate: 0.1, interval_seconds: 5, max_duration: 600, complete_on_timeout: true, price_strategy: 'PASSIVE' }
    case 'TARGET-POS-TASK':
      return { price_strategy: 'PASSIVE', offset_priority: '昨今' }
    default:
      return {}
  }
}

/**
 * 由 SINGLE-MAKER 的 params 反推意图档位，用于高亮意图卡；无法匹配时返回 `null`。
 *
 * 与 :func:`resolveAlgorithm` 的三档产物保持镜像：``fill`` 立即吃单不追、``save`` 被动
 * 挂单且等待封顶 3600s、``balance`` 被动挂单且追单。
 */
export function intentFromParams(params: Record<string, unknown>): Intent | null {
  const ps = params.price_strategy
  const chase = params.chase_enabled
  const wait = params.max_wait_seconds
  if (ps === 'ACTIVE' && chase === false) return 'fill'
  if (ps === 'PASSIVE' && chase === true) return wait === 3600 ? 'save' : 'balance'
  return null
}

/**
 * 算法引用人话摘要（编辑总览 / 详情入口用）。
 *
 * SINGLE-MAKER / TARGET-POS-TASK 能反推意图时用意图标题；否则用算法展示名。
 */
export function describeAlgorithmRef(ref: AlgorithmRef | null | undefined, market: Market): string {
  if (!ref?.method) return '未设置'
  if (ref.method === 'SINGLE-MAKER' || ref.method === 'TARGET-POS-TASK') {
    const intent = intentFromParams(ref.params ?? {})
    if (intent) return INTENT_COPY[market][intent].title
  }
  return algoLabel(ref.method)
}
