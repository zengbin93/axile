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

export const SINGLE_MAKER_DEFAULT_PARAMS: Readonly<Record<string, unknown>> = {
  price_strategy: 'ACTIVE',
  max_wait_seconds: 60,
  chase_enabled: false,
  chase_ticks: 1,
  max_chase_count: 5,
  chase_interval: 5,
  on_missing_book: 'skip',
}

export const TARGET_POS_DEFAULT_PARAMS: Readonly<Record<string, unknown>> = {
  price_strategy: 'PASSIVE',
  offset_priority: '昨今',
  max_wait_seconds: 60,
  chase_enabled: false,
  chase_ticks: 1,
  max_chase_count: 5,
  chase_interval: 5,
}

const SINGLE_MAKER_PARAM_KEYS = new Set(Object.keys(SINGLE_MAKER_DEFAULT_PARAMS))

/** 用服务端默认值补齐 SINGLE-MAKER 参数，仅供展示与语义比较。 */
export function effectiveSingleMakerParams(params: Record<string, unknown>): Record<string, unknown> {
  return { ...SINGLE_MAKER_DEFAULT_PARAMS, ...params }
}

/** 用服务端默认值补齐 TARGET-POS-TASK 参数。 */
export function effectiveTargetPosParams(params: Record<string, unknown>): Record<string, unknown> {
  return { ...TARGET_POS_DEFAULT_PARAMS, ...params }
}

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
    ...(market === 'ctp' ? { offset_priority: '昨今' } : {}),
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
 * 校验存在且相关的枚举、时长与追单参数，其余键忽略。返回首个违规文案；全部合法
 * 返回 `null`。用于在提交前拦下非法 params，避免重蹈「参数被后端吞成 dict、执行
 * 到算法内部才炸」的覆辙。
 */
export function validateAlgorithmParams(params: Record<string, unknown>): string | null {
  const num = (k: string): number | undefined => (typeof params[k] === 'number' ? (params[k] as number) : undefined)
  const has = (k: string): boolean => Object.prototype.hasOwnProperty.call(params, k)

  if (has('price_strategy') && params.price_strategy !== 'PASSIVE' && params.price_strategy !== 'ACTIVE') {
    return `下单价格（price_strategy）必须是 PASSIVE 或 ACTIVE`
  }
  if (has('offset_priority') && params.offset_priority !== '昨今' && params.offset_priority !== '今昨') {
    return `平仓优先（offset_priority）必须是 昨今 或 今昨`
  }
  if (has('on_missing_book') && !['skip', 'active', 'market'].includes(String(params.on_missing_book))) {
    return `盘口缺失策略（on_missing_book）必须是 skip、active 或 market`
  }
  if (has('chase_enabled') && typeof params.chase_enabled !== 'boolean') {
    return `追单开关（chase_enabled）必须是布尔值`
  }

  const wait = num('max_wait_seconds')
  if (has('max_wait_seconds') && wait === undefined) return `单次等待时间（max_wait_seconds）必须是数字`
  if (wait !== undefined && (!Number.isInteger(wait) || wait < 1 || wait > 3600)) {
    return `单次等待时间（max_wait_seconds）需为 1–3600 的整数，当前 ${wait}`
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
    if (has('chase_ticks') && ticks === undefined) return `价格偏离（chase_ticks）必须是数字`
    if (has('max_chase_count') && count === undefined) return `最大追单次数（max_chase_count）必须是数字`
    if (has('chase_interval') && interval === undefined) return `追单间隔（chase_interval）必须是数字`
    if (ticks !== undefined && (!Number.isInteger(ticks) || ticks < 1 || ticks > 100)) {
      return `启用追单时价格偏离（chase_ticks）需为 1–100 的整数，当前 ${ticks}`
    }
    if (count !== undefined && (!Number.isInteger(count) || count < 1 || count > 50)) {
      return `启用追单时最大追单次数（max_chase_count）需为 1–50 的整数，当前 ${count}`
    }
    if (interval !== undefined && (!Number.isFinite(interval) || interval < 0.1 || interval > 300)) {
      return `启用追单时追单间隔（chase_interval）需在 0.1–300s，当前 ${interval}`
    }
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
  if (market === 'ctp') {
    return { method: 'TARGET-POS-TASK', params: { ...TARGET_POS_DEFAULT_PARAMS, price_strategy: 'ACTIVE' } }
  }
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
      return { ...TARGET_POS_DEFAULT_PARAMS }
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
  if (Object.keys(params).some((key) => !SINGLE_MAKER_PARAM_KEYS.has(key))) return null

  const actual = effectiveSingleMakerParams(params)
  for (const intent of ['save', 'fill', 'balance'] as const) {
    const expected = effectiveSingleMakerParams(resolveAlgorithm(intent, 'crypto').params)
    const keys = actual.chase_enabled === false
      ? ['price_strategy', 'max_wait_seconds', 'chase_enabled', 'on_missing_book']
      : [...SINGLE_MAKER_PARAM_KEYS]
    if (keys.every((key) => actual[key] === expected[key])) return intent
  }
  return null
}

/** SINGLE-MAKER 当前有效参数的一句话摘要。 */
export function describeSingleMakerParams(params: Record<string, unknown>): string {
  const effective = effectiveSingleMakerParams(params)
  const price = effective.price_strategy === 'PASSIVE'
    ? '被动挂单'
    : effective.price_strategy === 'ACTIVE'
      ? '主动成交'
      : '下单价格异常'
  const wait = Number(effective.max_wait_seconds)
  const parts = [price, `等待 ${Number.isFinite(wait) ? wait : '—'} 秒`]
  if (effective.chase_enabled === true) {
    parts.push(`最多追单 ${String(effective.max_chase_count)} 次`)
  } else {
    parts.push('不追单')
  }
  if (effective.on_missing_book === 'active') parts.push('盘口缺失时按对手价成交')
  if (effective.on_missing_book === 'market') parts.push('盘口缺失时直接市价成交')
  return parts.join(' · ')
}

/** TARGET-POS-TASK 当前有效参数的一句话摘要。 */
export function describeTargetPosParams(params: Record<string, unknown>): string {
  const effective = effectiveTargetPosParams(params)
  const price = effective.price_strategy === 'ACTIVE' ? '主动吃单' : '被动挂单'
  const wait = Number(effective.max_wait_seconds)
  const parts = [price, `等待 ${Number.isFinite(wait) ? wait : '—'} 秒`]
  parts.push(effective.chase_enabled === true ? `最多追单 ${String(effective.max_chase_count)} 次` : '不追单')
  return parts.join(' · ')
}

/**
 * 算法引用人话摘要（编辑总览 / 详情入口用）。
 *
 * SINGLE-MAKER / TARGET-POS-TASK 能反推意图时用意图标题；否则用算法展示名。
 */
export function describeAlgorithmRef(ref: AlgorithmRef | null | undefined, market: Market): string {
  if (!ref?.method) return '未设置'
  if (ref.method === 'SINGLE-MAKER') {
    const intent = intentFromParams(ref.params ?? {})
    if (intent) return INTENT_COPY[market][intent].title
    return `${algoLabel(ref.method)}（自定义）`
  }
  if (ref.method === 'TARGET-POS-TASK') {
    return describeTargetPosParams(ref.params ?? {})
  }
  return algoLabel(ref.method)
}
