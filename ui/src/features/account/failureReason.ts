/**
 * 把执行失败的原始错误翻成人话（纯函数，与组件解耦、便于测试）。
 *
 * 后端只给到 7 类 `reason_family` + 阶段级 `reason_code`，真正的失败原因是一条裸串
 * （`details.debug.error`，交易所/系统原文）。这里按签名把高价值错误归类成
 * 「类别 / 人话 / 归谁 / 可否重试 / 下一步」，让「偏离」头条点进来后能回答「为什么」。
 *
 * FP：交易所错误码稳定（如 -1021），是纯函数、可复用；先在前端立起翻译，稳定后可提升进后端事件。
 */
import type { ExecutionEvent } from '@/types/api'

/** 失败归责方（不含「环境」——时钟 / 网络等基础设施噪声不在此分类，见 PATTERNS 注释）。 */
export type FailureBlame = 'exchange' | 'account' | 'input' | 'system'

/** 归责人话。 */
export const BLAME_LABEL: Record<FailureBlame, string> = {
  exchange: '交易所',
  account: '账户',
  input: '输入',
  system: '系统',
}

/** 翻译后的失败判词。 */
export interface FailureReason {
  /** 归类短标（时钟偏移 / 密钥权限 / 保证金 …）。 */
  category: string
  /** 人话主因。 */
  human: string
  /** 归谁：环境 / 交易所 / 账户 / 输入 / 系统。 */
  blame: FailureBlame
  /** 是否可原样重试（修好前置后）。 */
  retryable: boolean
  /** 下一步动作。 */
  action: string
  /** 原始错误串（取证 / 兜底展示）。 */
  raw: string
}

/** 从失败事件里抠出原始错误串与后端标注的可重试位（兼容裸串与 worker 对象两种形态）。 */
function rawErrorOf(e: ExecutionEvent): { text: string; retryable: boolean | null } {
  const debug = (e.details as { debug?: unknown } | undefined)?.debug
  const err = debug && typeof debug === 'object' ? (debug as { error?: unknown }).error : undefined
  if (typeof err === 'string') return { text: err, retryable: null }
  if (err && typeof err === 'object') {
    const o = err as { message?: unknown; type?: unknown; retryable?: unknown }
    const parts = [o.type, o.message].filter((x): x is string => typeof x === 'string')
    return { text: parts.join(': '), retryable: typeof o.retryable === 'boolean' ? o.retryable : null }
  }
  return { text: '', retryable: null }
}

interface Pattern {
  test: RegExp
  category: string
  human: string
  blame: FailureBlame
  retryable: boolean
  action: string
}

/**
 * 高价值错误签名表（顺序匹配，先中先出）。
 *
 * 注意：-1021 等时钟 / 基础设施噪声刻意**不**列在此。那不是交易结果，是「管道漏了」——应在源头
 * （同步系统时钟 / rest_client）消灭，而非在产品里翻译。翻译它 = 把 bug 装裱成 feature；漏进来时
 * 走兜底、原样呈现，读起来就是「上游该修」。
 */
const PATTERNS: Pattern[] = [
  {
    test: /-2015|-2014|invalid api[- ]?key|api[- ]?key.*ip|not white ?listed/i,
    category: '密钥/权限',
    human: 'API Key 无效、权限不足或 IP 未加白',
    blame: 'account',
    retryable: false,
    action: '检查 API Key、权限范围与 IP 白名单',
  },
  {
    test: /-1022|signature for this request/i,
    category: '签名',
    human: '请求签名无效',
    blame: 'account',
    retryable: false,
    action: '检查 API Secret 是否正确',
  },
  {
    test: /-2019|margin is insufficient|-2018|insufficient balance/i,
    category: '保证金不足',
    human: '可用保证金 / 余额不足以下单',
    blame: 'account',
    retryable: false,
    action: '补充保证金或下调目标仓位',
  },
  {
    test: /-1013|-4164|min[_ ]?notional|notional must be no smaller/i,
    category: '低于最小名义',
    human: '下单名义低于交易所最小值',
    blame: 'input',
    retryable: false,
    action: '提高该品种目标权重，或将其排除',
  },
  {
    test: /-1111|precision|lot[_ ]?size|min[_ ]?qty|step[_ ]?size/i,
    category: '精度 / 最小量',
    human: '下单数量不满足精度或最小下单量',
    blame: 'input',
    retryable: false,
    action: '检查数量精度与最小下单量',
  },
]

/** reason_family 兜底归责。 */
function familyBlame(family: string): FailureBlame {
  switch (family) {
    case 'EXCHANGE':
      return 'exchange'
    case 'ACCOUNT_STATE':
      return 'account'
    case 'INPUT':
    case 'RISK':
    case 'MARKET_RULE':
      return 'input'
    default:
      return 'system'
  }
}

/**
 * 把一条 `execution_failed` 事件翻成人话失败判词.

 * Parameters
 * ----------
 * event : ExecutionEvent | null | undefined
 *     生命周期失败事件（``execution_failed``）；``null``/``undefined`` 表示本次执行未在此层失败。

 * Returns
 * -------
 * FailureReason | null
 *     结构化失败判词；无失败事件时返回 ``null``。后端 worker 路径若明确给了 ``retryable``，
 *     以它为准，否则用签名表判定。
 */
export function describeFailure(event: ExecutionEvent | null | undefined): FailureReason | null {
  if (!event) return null
  const { text, retryable } = rawErrorOf(event)
  const haystack = `${text} ${event.reason_code} ${event.reason_family}`
  for (const p of PATTERNS) {
    if (p.test.test(haystack)) {
      return {
        category: p.category,
        human: p.human,
        blame: p.blame,
        retryable: retryable ?? p.retryable,
        action: p.action,
        raw: text,
      }
    }
  }
  return {
    category: '未归类',
    human: text || '执行失败（无错误详情）',
    blame: familyBlame(event.reason_family),
    retryable: retryable ?? false,
    action: '查看下方原始错误',
    raw: text,
  }
}
