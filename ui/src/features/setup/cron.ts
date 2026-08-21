import { getChannelDescriptor } from '@/stores/channels'

/**
 * 定时节奏 → crontab 编译（从原型移植为纯函数）。
 *
 * 第一性原理：执行时刻 = 策略 bar 收盘时刻 = f(频率, 市场交易时段)。
 * 前台只给「市场感知的快捷预设」，底层编译成 APScheduler 可用的 crontab（北京时间）。
 * 多条规则用 ``|`` 拼接（后端 `parse_cron_expr` 支持）。
 */

export type Market = 'crypto' | 'ashare' | 'ctp'

/** 自定义节奏可选频率。 */
export type CustomFreq = 'm15' | 'm60' | 'm120' | 'm240' | 'd1'

/** 自定义节奏锚点（日线/4 小时线取开盘或临收）。 */
export type Anchor = 'open' | 'close'

/** 渠道 → 市场。 */
export const CHANNEL_MARKET: Record<string, Market> = {
  ctp: 'ctp',
  gm: 'ashare',
}

/** 从运行时渠道目录解析市场；目录未就绪时兼容公开内置渠道。 */
export function marketForChannel(channel: string): Market {
  const market = getChannelDescriptor(channel)?.market ?? CHANNEL_MARKET[channel]
  if (market === 'ashare' || market === 'ctp' || market === 'crypto') return market
  return 'crypto'
}

export const MARKET_NAME: Record<Market, string> = {
  crypto: '加密（24/7）',
  ashare: 'A股',
  ctp: '期货（CTP）',
}

/** 各市场默认预设 id。 */
export const DEFAULT_PRESET: Record<Market, string> = {
  crypto: 'd1',
  ctp: 'close',
  ashare: 'open',
}

/** 市场交易时段内的 bar 收盘时刻。 */
const SESS = {
  ashare: {
    open: '09:30',
    close: '14:50',
    dayClose: '15:00',
    dow: '1-5',
    m15: ['09:45', '10:00', '10:15', '10:30', '10:45', '11:00', '11:15', '11:30', '13:15', '13:30', '13:45', '14:00', '14:15', '14:30', '14:45', '15:00'],
    m60: ['10:30', '11:30', '14:00', '15:00'],
    m120: ['11:30', '15:00'],
  },
  ctp: {
    open: '09:00',
    close: '15:00',
    dayClose: '15:00',
    dow: '1-5',
    m15: ['09:15', '09:30', '09:45', '10:00', '10:15', '10:30', '10:45', '11:00', '11:15', '11:30', '13:45', '14:00', '14:15', '14:30', '14:45', '15:00'],
    m60: ['10:00', '11:00', '14:30', '15:00'],
    m120: ['11:30', '15:00'],
  },
}

/** 补发偏移集合：0（到点）+ N 次每隔 M 分。 */
function supOffsets(supN: number, supM: number): number[] {
  return [0, ...Array.from({ length: supN }, (_, k) => (k + 1) * supM)]
}

/** 加密：分钟基点 + 偏移 → 同小时内分钟列表。 */
function cyMins(base: number[], offs: number[]): string {
  return [...new Set(base.flatMap((b) => offs.map((o) => (b + o) % 60)))].sort((a, b) => a - b).join(',')
}

/** 一组 HH:MM × 偏移集 → 按分钟分组的 cron 列表。 */
function timesToCron(times: string[], dow: string, offs: number[]): string[] {
  const byMin: Record<number, number[]> = {}
  for (const t of times) {
    const [H, M] = t.split(':').map(Number)
    for (const o of offs) {
      let m = M + o
      let h = H + Math.floor(m / 60)
      m = ((m % 60) + 60) % 60
      h = ((h % 24) + 24) % 24
      ;(byMin[m] = byMin[m] || []).push(h)
    }
  }
  return Object.keys(byMin)
    .map(Number)
    .sort((a, b) => a - b)
    .map((m) => `${m} ${[...new Set(byMin[m])].sort((a, b) => a - b).join(',')} * * ${dow}`)
}

export interface Preset {
  id: string
  label: string
  sub?: string
  build: (offs: number[]) => string[]
}

/** 市场感知的快捷预设。 */
export const PRESETS: Record<Market, Preset[]> = {
  crypto: [
    { id: 'm15', label: '每 15 分钟', sub: '每 15 分', build: (o) => [`${cyMins([0, 15, 30, 45], o)} * * * *`] },
    { id: 'h1', label: '每小时', sub: ':00 起', build: (o) => [`${cyMins([0], o)} * * * *`] },
    { id: 'h4', label: '每 4 小时', sub: '*/4 时', build: (o) => [`${cyMins([0], o)} */4 * * *`] },
    { id: 'd1', label: '每天', sub: '08:00', build: (o) => [`${cyMins([0], o)} 8 * * *`] },
  ],
  ashare: [
    { id: 'open', label: '每交易日 · 开盘', sub: '09:30', build: (o) => timesToCron([SESS.ashare.open], '1-5', o) },
    { id: 'close', label: '每交易日 · 临收', sub: '14:50', build: (o) => timesToCron([SESS.ashare.close], '1-5', o) },
    { id: 'm15', label: '盘中每 15 分', build: (o) => timesToCron(SESS.ashare.m15, '1-5', o) },
    { id: 'm60', label: '盘中每 60 分', build: (o) => timesToCron(SESS.ashare.m60, '1-5', o) },
  ],
  ctp: [
    { id: 'close', label: '日盘收盘', sub: '15:00', build: (o) => timesToCron([SESS.ctp.dayClose], '1-5', o) },
    { id: 'm15', label: '日盘每 15 分', build: (o) => timesToCron(SESS.ctp.m15, '1-5', o) },
    { id: 'm60', label: '日盘每 60 分', build: (o) => timesToCron(SESS.ctp.m60, '1-5', o) },
  ],
}

/** 由所选预设 + 补发参数编译出 cron 列表。 */
export function buildCronList(
  market: Market,
  presetIds: string[],
  supN: number,
  supM: number,
): string[] {
  const offs = supOffsets(supN, supM)
  let out: string[] = []
  for (const id of presetIds) {
    const p = PRESETS[market].find((x) => x.id === id)
    if (p) out = out.concat(p.build(offs))
  }
  return out
}

/**
 * 自定义节奏（频率 + 锚点）编译为 cron 列表，仍按市场时段落点。

 * Parameters
 * ----------
 * market : Market
 *     目标市场；``crypto`` 走纯分钟/小时表达式，其余按交易时段编译。
 * freq : CustomFreq
 *     频率档位。
 * anchor : Anchor
 *     日线 / 4 小时线的锚点（开盘或临收），仅在时段市场生效。
 * supN, supM : number
 *     补发次数与间隔（分钟）。
 *
 * Returns
 * -------
 * string[]
 *     一条或多条 crontab 规则。
 */
export function compileCustom(
  market: Market,
  freq: CustomFreq,
  anchor: Anchor,
  supN: number,
  supM: number,
): string[] {
  return compileScheduleRule(
    market,
    {
      id: '_',
      freq,
      time: freq === 'd1' ? (market === 'crypto' ? '08:00' : anchor === 'close' ? (market === 'ashare' ? '14:50' : '15:00') : market === 'ashare' ? '09:30' : '09:00') : '00:00',
      days: [],
      anchor,
      draft: false,
    },
    supN,
    supM,
  )
}

/* ------------------ 高级：结构化时间规则 ------------------ */

/** 定时页 tab。 */
export type TimerTab = 'quick' | 'advanced'

/**
 * 高级编辑器中的一条时间规则。
 *
 * ``draft: true`` 表示空槽（未填完），编译时跳过；日频须有合法 ``time``。
 */
export interface ScheduleRule {
  id: string
  freq: CustomFreq
  /** HH:MM；日频必填，周期类可忽略。 */
  time: string
  /** 周几掩码：0=日 … 6=六；空数组 = 市场默认（crypto 每天 / 时段市场工作日）。 */
  days: number[]
  /** 时段市场日频/4h 锚点（有合法 time 时优先用 time）。 */
  anchor: Anchor
  /** 空槽：未完成，不参与编译。 */
  draft: boolean
}

const FREQ_LABEL: Record<CustomFreq, string> = {
  m15: '每 15 分钟',
  m60: '每小时',
  m120: '每 2 小时',
  m240: '每 4 小时',
  d1: '每天',
}

/** 生成规则 id。 */
export function newRuleId(): string {
  return `r_${Math.random().toString(36).slice(2, 10)}`
}

/** 校验 HH:MM。 */
export function isValidTime(time: string): boolean {
  const m = /^(\d{1,2}):(\d{2})$/.exec(time.trim())
  if (!m) return false
  const h = Number(m[1])
  const min = Number(m[2])
  return h >= 0 && h <= 23 && min >= 0 && min <= 59
}

/** 规则是否可编译（非空槽且参数齐全）。 */
export function isRuleComplete(rule: ScheduleRule): boolean {
  if (rule.draft) return false
  if (rule.freq === 'd1') return isValidTime(rule.time)
  return true
}

/** 周几 → cron 第 5 段；空 = 市场默认。 */
export function daysToCronField(days: number[], market: Market): string {
  if (!days.length) return market === 'crypto' ? '*' : '1-5'
  const sorted = [...new Set(days)].sort((a, b) => a - b)
  if (sorted.length === 7) return '*'
  return sorted.join(',')
}

/** 市场默认一条完整规则（进高级 / 重置用）。 */
export function defaultScheduleRule(market: Market): ScheduleRule {
  if (market === 'crypto') {
    return { id: newRuleId(), freq: 'd1', time: '08:00', days: [], anchor: 'open', draft: false }
  }
  if (market === 'ashare') {
    return { id: newRuleId(), freq: 'd1', time: '09:30', days: [1, 2, 3, 4, 5], anchor: 'open', draft: false }
  }
  return { id: newRuleId(), freq: 'd1', time: '15:00', days: [1, 2, 3, 4, 5], anchor: 'close', draft: false }
}

/** 由快捷预设 id 展开为一条高级规则。 */
export function ruleFromPreset(market: Market, presetId: string): ScheduleRule {
  const base = defaultScheduleRule(market)
  if (market === 'crypto') {
    if (presetId === 'm15') return { ...base, id: newRuleId(), freq: 'm15', time: '00:00' }
    if (presetId === 'h1') return { ...base, id: newRuleId(), freq: 'm60', time: '00:00' }
    if (presetId === 'h4') return { ...base, id: newRuleId(), freq: 'm240', time: '00:00' }
    return { ...base, id: newRuleId(), freq: 'd1', time: '08:00' }
  }
  if (market === 'ashare') {
    if (presetId === 'm15') return { ...base, id: newRuleId(), freq: 'm15', time: '00:00' }
    if (presetId === 'm60') return { ...base, id: newRuleId(), freq: 'm60', time: '00:00' }
    if (presetId === 'close') return { ...base, id: newRuleId(), freq: 'd1', time: '14:50', anchor: 'close' }
    return { ...base, id: newRuleId(), freq: 'd1', time: '09:30', anchor: 'open' }
  }
  if (presetId === 'm15') return { ...base, id: newRuleId(), freq: 'm15', time: '00:00' }
  if (presetId === 'm60') return { ...base, id: newRuleId(), freq: 'm60', time: '00:00' }
  return { ...base, id: newRuleId(), freq: 'd1', time: '15:00', anchor: 'close' }
}

/**
 * 基于已有规则生成空槽（进组合时的第 2 项 / 「再加一条」）。
 * 继承重复维度，日频时刻留空待填。
 */
export function makeEmptySlot(from: ScheduleRule): ScheduleRule {
  return {
    id: newRuleId(),
    freq: 'd1',
    time: '',
    days: [...from.days],
    anchor: from.anchor,
    draft: true,
  }
}

/** 规则人话短标签（右栏列表用）。 */
export function describeRule(rule: ScheduleRule): string {
  if (rule.draft && !isValidTime(rule.time)) return '未完成'
  const dayBit = rule.days.length && rule.days.length < 7
    ? `周${rule.days
        .slice()
        .sort((a, b) => a - b)
        .map((d) => '日一二三四五六'[d])
        .join('')}`
    : ''
  if (rule.freq === 'd1') {
    const t = isValidTime(rule.time) ? rule.time : '—:—'
    return dayBit ? `${dayBit} ${t}` : `每天 ${t}`
  }
  const core = FREQ_LABEL[rule.freq]
  return dayBit ? `${core} · ${dayBit}` : core
}

/**
 * 将一条结构化规则编译为 crontab。
 *
 * 日频用 ``time``；周期类按市场 bar 表或 crypto 整点表达式；``days`` 写入周字段。
 */
export function compileScheduleRule(
  market: Market,
  rule: ScheduleRule,
  supN: number,
  supM: number,
): string[] {
  if (!isRuleComplete(rule)) return []
  const offs = supOffsets(supN, supM)
  const dow = daysToCronField(rule.days, market)

  if (market === 'crypto') {
    if (rule.freq === 'd1') {
      return timesToCron([rule.time.trim()], dow, offs)
    }
    const base: Record<Exclude<CustomFreq, 'd1'>, number[]> = {
      m15: [0, 15, 30, 45],
      m60: [0],
      m120: [0],
      m240: [0],
    }
    const hr: Record<Exclude<CustomFreq, 'd1'>, string> = {
      m15: '*',
      m60: '*',
      m120: '*/2',
      m240: '*/4',
    }
    const f = rule.freq as Exclude<CustomFreq, 'd1'>
    return [`${cyMins(base[f], offs)} ${hr[f]} * * ${dow}`]
  }

  const S = market === 'ashare' ? SESS.ashare : SESS.ctp
  // 时段市场：日频若有合法时刻则按钟点；否则回退锚点开盘/临收。
  if (rule.freq === 'd1' || rule.freq === 'm240') {
    if (rule.freq === 'd1' && isValidTime(rule.time)) {
      return timesToCron([rule.time.trim()], dow, offs)
    }
    const t = rule.anchor === 'close' ? S.close : S.open
    return timesToCron([t], dow, offs)
  }
  if (rule.freq === 'm15') return timesToCron(S.m15, dow, offs)
  if (rule.freq === 'm120') return timesToCron(S.m120, dow, offs)
  return timesToCron(S.m60, dow, offs)
}

/** 编译高级规则列表（跳过空槽）。 */
export function compileScheduleRules(
  market: Market,
  rules: ScheduleRule[],
  supN: number,
  supM: number,
): string[] {
  return rules.flatMap((r) => compileScheduleRule(market, r, supN, supM))
}

/**
 * 定时「意图」：快捷预设 / 高级规则列表 / 裸 cron / 补发。

 * Notes
 * -----
 * 向导跨步骤保存此意图以便回显与再编辑；``cron_expr`` 由 :func:`resolveCronList` 现算。
 * 优先级：自定义表达式（customCronOn + rawCron）> 高级 tab 规则 > 快捷预设。
 */
export interface TimerIntent {
  presetIds: string[]
  supN: number
  supM: number
  rawCron: string
  /** 快捷 | 高级；缺省时若仅有 rawCron 则按表达式（编辑页）。 */
  timerTab?: TimerTab
  /** 高级：时间规则列表；长度 ≥2 时 UI 显示右栏组合列表。 */
  scheduleRules?: ScheduleRule[]
  /** 高级右栏当前选中的规则 id。 */
  selectedRuleId?: string
  /** 高级底部「自定义模式」：开启后以 rawCron 为准。 */
  customCronOn?: boolean
  /**
   * @deprecated 兼容旧测试/调用：等价于「高级 + 单条 customFreq 规则」。
   * resolve 时若未提供 scheduleRules 且 customOn，仍走 compileCustom。
   */
  customOn?: boolean
  customFreq?: CustomFreq
  customAnchor?: Anchor
}

/**
 * 按优先级收敛出 cron 列表：自定义表达式 > 高级规则 > 旧 customOn > 预设。

 * Parameters
 * ----------
 * market : Market
 *     目标市场。
 * t : TimerIntent
 *     定时意图。
 *
 * Returns
 * -------
 * string[]
 *     crontab 规则列表；均为空时返回空数组。
 */
export function resolveCronList(market: Market, t: TimerIntent): string[] {
  const raw = t.rawCron.trim()
  // 自定义模式开，或以「无 tab / 无高级规则」的裸表达式路径（账户编辑页）。
  if (raw && (t.customCronOn || (t.timerTab == null && !t.scheduleRules?.length && !t.customOn))) {
    return raw
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (t.timerTab === 'advanced' && t.scheduleRules?.length) {
    return compileScheduleRules(market, t.scheduleRules, t.supN, t.supM)
  }
  if (t.customOn && t.customFreq) {
    return compileCustom(market, t.customFreq, t.customAnchor ?? 'open', t.supN, t.supM)
  }
  if (raw && !t.timerTab) {
    return raw
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  return buildCronList(market, t.presetIds, t.supN, t.supM)
}

/**
 * 校验裸 crontab：每条规则须为 5 段（分 时 日 月 周）。

 * Parameters
 * ----------
 * raw : str
 *     裸 crontab 文本，多条用 ``|`` 分隔。

 * Returns
 * -------
 * str | None
 *     不合法时返回错误提示；合法或为空时返回 ``None``。
 */
export function cronError(raw: string): string | null {
  const rules = raw
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean)
  const bad = rules.some((s) => s.split(/\s+/).length !== 5)
  return bad ? 'cron 格式有误：每条规则须为 5 段（分 时 日 月 周）。' : null
}

/** 拼成后端要的单字符串（`|` 分隔）。 */
export function cronToExpr(list: string[]): string {
  return list.join(' | ')
}

/* ------------------ 下次触发预览 ------------------ */

function matchField(expr: string, val: number): boolean {
  if (expr === '*') return true
  return expr.split(',').some((p) => {
    if (p.includes('/')) {
      const [rng, stp] = p.split('/')
      const n = parseInt(stp, 10)
      let lo = 0
      let hi = 59
      if (rng !== '*') {
        if (rng.includes('-')) {
          const a = rng.split('-')
          lo = +a[0]
          hi = +a[1]
        } else lo = hi = +rng
      }
      return val >= lo && val <= hi && (val - lo) % n === 0
    }
    if (p.includes('-')) {
      const a = p.split('-')
      return val >= +a[0] && val <= +a[1]
    }
    return +p === val
  })
}

function cronMatch(f: string[], d: Date): boolean {
  return (
    matchField(f[0], d.getMinutes()) &&
    matchField(f[1], d.getHours()) &&
    matchField(f[2], d.getDate()) &&
    matchField(f[3], d.getMonth() + 1) &&
    matchField(f[4].replace(/7/g, '0'), d.getDay())
  )
}

/** 计算未来 count 个触发时刻（本地时钟近似，用于预览）。 */
export function nextFires(list: string[], count: number): Date[] {
  const F = list.map((c) => c.trim().split(/\s+/)).filter((a) => a.length === 5)
  if (!F.length) return []
  const res: Date[] = []
  const d = new Date()
  d.setSeconds(0, 0)
  d.setMinutes(d.getMinutes() + 1)
  for (let i = 0; i < 60 * 24 * 40 && res.length < count; i++) {
    if (F.some((f) => cronMatch(f, d))) res.push(new Date(d))
    d.setMinutes(d.getMinutes() + 1)
  }
  return res
}

/** 格式化触发时刻为「今天/明天 HH:MM」。 */
export function fmtFire(d: Date): string {
  const now = new Date()
  const a = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const b = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = Math.round((b.getTime() - a.getTime()) / 864e5)
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const day =
    diff === 0 ? '今天' : diff === 1 ? '明天' : diff === 2 ? '后天' : `周${'日一二三四五六'[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`
  return `${day} ${hm}`
}

/* ------------------ cron → 人话反解 ------------------ */

/** 规范化单条 cron：把逗号列表排序去重，其余段原样，便于与正向编译产物字符串比对。 */
function normCronLine(line: string): string {
  const seg = line.trim().split(/\s+/)
  if (seg.length !== 5) return line.trim()
  return seg
    .map((s) => (s.includes(',') ? [...new Set(s.split(','))].map(Number).sort((a, b) => a - b).join(',') : s))
    .join(' ')
}

/** 规范化整份 cron（多条以 `|` 或换行分隔）为可比较的稳定串。 */
function normCronSet(expr: string): string {
  return [...new Set(expr.split(/[|\n]/).map(normCronLine).filter(Boolean))].sort().join(' | ')
}

/** 补发档位（与设置向导下拉一致），用于穷举反解。 */
const SUP_N = [0, 1, 2, 3, 4]
const SUP_M = [1, 2, 3, 5]

/**
 * 反解 cron 为设置向导同款人话（预设名 + 补发次数）。
 *
 * 复用正向 {@link buildCronList} 穷举「单预设 × 补发档位」，规范化后与目标比对，命中即
 * 得如「每 15 分钟 · 补发 2 次」的短语；命不中任何预设组合（多选 / 自定义节奏 / 裸 cron）
 * 时返回 ``null``，由上层降级为「自定义 + 下次触发预览」。
 *
 * @param market 目标市场，决定候选预设集。
 * @param cronExpr 存储的 crontab（多条以 `|` 或换行分隔）。
 * @returns 人话短语；无法归类时为 ``null``。
 */
export function describeCron(market: Market, cronExpr: string): string | null {
  const target = normCronSet(cronExpr)
  if (!target) return null
  for (const p of PRESETS[market]) {
    for (const n of SUP_N) {
      for (const m of SUP_M) {
        if (normCronSet(buildCronList(market, [p.id], n, m).join(' | ')) !== target) continue
        const time = p.sub && /^\d{1,2}:\d{2}$/.test(p.sub) ? ` ${p.sub}` : ''
        return n > 0 ? `${p.label}${time} · 补发 ${n} 次` : `${p.label}${time}`
      }
    }
  }
  return null
}

/* ------------------ cron → 编辑器意图反解（账户编辑页） ------------------ */

/**
 * 定时编辑器完整状态：在 :interface:`TimerIntent` 上增加「自动调仓」总开关。
 *
 * 空 ``cron_expr`` 对应 ``autoOn: false``（仅手动）；有表达式则 ``autoOn: true`` 并尽量回填
 * 快捷预设 / 高级规则 / 自定义模式。
 */
export interface TimerEditorState extends TimerIntent {
  autoOn: boolean
  timerTab: TimerTab
  scheduleRules: ScheduleRule[]
  selectedRuleId: string
  customCronOn: boolean
}

/** 构造一份「关自动 + 市场默认节奏」草稿（打开开关后可立刻用）。 */
export function defaultTimerEditorState(market: Market): TimerEditorState {
  const rule = defaultScheduleRule(market)
  return {
    autoOn: false,
    presetIds: [DEFAULT_PRESET[market]],
    supN: 0,
    supM: 1,
    rawCron: '',
    timerTab: 'quick',
    scheduleRules: [rule],
    selectedRuleId: rule.id,
    customCronOn: false,
  }
}

/** 解析 cron 第 5 段（周）为 days 掩码；无法识别返回 null。 */
function parseDowField(dow: string, market: Market): number[] | null {
  if (dow === '*') return []
  // 时段市场默认工作日 → 空数组（UI 显示市场默认）；crypto 则显式 1-5。
  if (dow === '1-5') return market === 'crypto' ? [1, 2, 3, 4, 5] : []
  if (!/^\d+(,\d+)*$/.test(dow)) return null
  const days = [...new Set(dow.split(',').map(Number))].filter((d) => d >= 0 && d <= 6).sort((a, b) => a - b)
  return days.length ? days : null
}

/**
 * 尝试把「每条均为单一时刻」的 cron 反解成高级日频规则列表。
 *
 * 仅支持 ``M H * * DOW``（分/时为单个数字）；列表分钟、步长、DOM/MON 非 ``*`` 时放弃。
 */
function tryParseDailyRules(market: Market, cronExpr: string): ScheduleRule[] | null {
  const lines = cronExpr
    .split(/[|\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (!lines.length) return null
  const rules: ScheduleRule[] = []
  for (const line of lines) {
    const parts = line.split(/\s+/)
    if (parts.length !== 5) return null
    const [min, hour, dom, mon, dow] = parts
    if (dom !== '*' || mon !== '*') return null
    if (!/^\d{1,2}$/.test(min) || !/^\d{1,2}$/.test(hour)) return null
    const days = parseDowField(dow, market)
    if (days == null) return null
    const h = Number(hour)
    const m = Number(min)
    if (h > 23 || m > 59) return null
    const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
    rules.push({
      id: newRuleId(),
      freq: 'd1',
      time,
      days,
      anchor: 'open',
      draft: false,
    })
  }
  return rules
}

/**
 * 穷举单预设 × 补发档位，命中则返回快捷 tab 意图。
 */
function tryMatchPreset(
  market: Market,
  target: string,
): Pick<TimerEditorState, 'presetIds' | 'supN' | 'supM'> | null {
  for (const p of PRESETS[market]) {
    for (const n of SUP_N) {
      for (const m of SUP_M) {
        if (normCronSet(buildCronList(market, [p.id], n, m).join(' | ')) === target) {
          return { presetIds: [p.id], supN: n, supM: m }
        }
      }
    }
  }
  return null
}

/**
 * 从存储的 ``cron_expr`` 反解为定时编辑器状态（向导 / 账户编辑共用）。
 *
 * 优先级：空 → 关自动；单预设+补发 → 快捷；纯日频多时刻 → 高级规则；其余 → 高级+自定义表达式。
 *
 * Parameters
 * ----------
 * market : Market
 *     账户市场，决定预设集与默认规则。
 * cronExpr : str
 *     后端存的 crontab（``|`` 或换行分隔）。
 *
 * Returns
 * -------
 * TimerEditorState
 *     可直接喂给 :component:`TimerEditor` 的完整状态。
 */
export function parseTimerIntent(market: Market, cronExpr: string): TimerEditorState {
  const trimmed = (cronExpr ?? '').trim()
  if (!trimmed) return defaultTimerEditorState(market)

  const target = normCronSet(trimmed)
  const hit = tryMatchPreset(market, target)
  if (hit) {
    const rule = ruleFromPreset(market, hit.presetIds[0]!)
    return {
      autoOn: true,
      ...hit,
      rawCron: '',
      timerTab: 'quick',
      scheduleRules: [rule],
      selectedRuleId: rule.id,
      customCronOn: false,
    }
  }

  const daily = tryParseDailyRules(market, trimmed)
  if (daily?.length) {
    return {
      autoOn: true,
      presetIds: [DEFAULT_PRESET[market]],
      supN: 0,
      supM: 1,
      rawCron: '',
      timerTab: 'advanced',
      scheduleRules: daily,
      selectedRuleId: daily[0]!.id,
      customCronOn: false,
    }
  }

  // 无法结构化：进高级自定义模式，保留原表达式（| 归一）。
  const rule = defaultScheduleRule(market)
  const raw = trimmed
    .split(/[|\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join(' | ')
  return {
    autoOn: true,
    presetIds: [DEFAULT_PRESET[market]],
    supN: 0,
    supM: 1,
    rawCron: raw,
    timerTab: 'advanced',
    scheduleRules: [rule],
    selectedRuleId: rule.id,
    customCronOn: true,
  }
}

/**
 * 将编辑器状态编译为后端 ``cron_expr``；关自动返回空串。
 */
export function timerStateToCronExpr(market: Market, state: TimerEditorState): string {
  if (!state.autoOn) return ''
  return cronToExpr(resolveCronList(market, state))
}

/**
 * 比较两份 cron 表达式是否语义相同（忽略分隔符、空白、条目顺序与逗号段内排序）。
 */
export function cronExprEqual(a: string, b: string): boolean {
  return normCronSet(a) === normCronSet(b)
}
