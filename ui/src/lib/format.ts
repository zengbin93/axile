/** 通用格式化助手。 */

/** 带正负号的整数百分数（净敞口/敞口用）。 */
export function signedPct(v: number): string {
  return `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(0)}%`
}

/**
 * 紧凑金额：`>=1亿` 用「亿」、`>=1万` 用「万」，其余千分位整数、极小值两位小数。
 *
 * 方向由调用方另行表达，这里只格式化幅度。
 */
export function fmtMoney(v: number): string {
  const a = Math.abs(v)
  if (a >= 1e8) return `${(a / 1e8).toFixed(1)}亿`
  if (a >= 1e4) return `${(a / 1e4).toFixed(1)}万`
  if (a >= 1) return Math.round(a).toLocaleString('zh-CN')
  return a.toFixed(2)
}

/**
 * 给金额数字缀简短货币记号：人民币用前缀「¥」，私有渠道计价币用后缀「U」。
 *
 * 只用于行内钱数的「就地确认」；头部权益另用渠道声明的全称当权威锚。其它币种原样
 * 空格后缀，`currency` 为空则不缀。
 */
export function withCurrency(numStr: string, currency: string): string {
  if (/^USD.$/.test(currency)) return `${numStr}U`
  if (currency === 'CNY') return `¥${numStr}`
  return currency ? `${numStr} ${currency}` : numStr
}

/** 金额直接带货币记号（`fmtMoney` + `withCurrency` 的组合便捷式）。 */
export function money(v: number, currency: string): string {
  return withCurrency(fmtMoney(v), currency)
}

/** 把过去的时间戳（ms）格式化为「N 秒前 / N 分钟前」。 */
export function timeAgo(ts: number | null, now = Date.now()): string {
  if (ts == null) return '—'
  const sec = Math.max(0, Math.round((now - ts) / 1000))
  if (sec < 60) return `${sec} 秒前`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr} 小时前`
  return `${Math.round(hr / 24)} 天前`
}
