/**
 * 从后端原始数据派生 UI 语义。
 *
 * 后端不下发「到位/背离」verdict，也无手续费汇总（见方案已知缺口）；这里用
 * 现有字段做诚实的粗粒度派生：能确定的说确定，不能确定的不编。
 */
import type { AccountDashboardItem, ExecuteRecord, LatestWeights, Position } from '@/types/api'

/**
 * 规整后端返回的账户计价货币.

 * Parameters
 * ----------
 * currency : string | null | undefined
 *     后端账户或资产快照返回的计价货币。

 * Returns
 * -------
 * str
 *     计价货币代码（``USDT``/``CNY``），拿不到渠道时返回 ``''``。
 */
export function currencyOf(currency: string | null | undefined): string {
  return currency?.trim() ?? ''
}

export type StatusLevel = 'ok' | 'warn' | 'bad' | 'run'

/* ==================== 账户两轴：在位性 ⊥ 档位 ==================== */

/**
 * 在位性轴：账户此刻在不在你要它待的位置（观察到的现实）。
 *
 * 「风险」轴——钱对不对得上意图，是新闻、可行动、该不可遮。与档位（自动/暂停）正交：
 * 账户可以「暂停且偏离」（最坏格：偏了又不会自愈），也可以「自动且偏离」（会自动纠正）。
 */
export type Integrity = 'aligned' | 'off' | 'unknown' // 在位 / 偏离 / 未知

/** 自动化档位轴：账户会不会自己执行（你设的模式，是上下文不是风险）。 */
export type Gate = 'auto' | 'paused' // 自动 / 暂停

/** 在位性判定。 */
export interface IntegrityStatus {
  integrity: Integrity
  /** 风险轴基础判词；模式相关的加重措辞（象限合成）留待渲染层，不在此定死。 */
  text: string
}

/** 档位判定。 */
export interface GateStatus {
  gate: Gate
  /** 模式短标，给账户名旁的安静 chip 用。 */
  label: string
}

/**
 * 从仪表盘项派生**在位性**（风险轴）。
 *
 * 只认执行结果（`last_is_success`/`last_exec_at`），**刻意不看 `is_started`**——
 * 这正是修掉「暂停吃掉失败」的关键：暂停是模式，遮不住偏离。
 *
 * 诚实律：默认「未知」，「在位」要靠证据挣——仅上次执行明确成功（`last_is_success===1`）
 * 才敢称在位；明确失败（`===0`）即偏离；其余（无记录/结果缺失）一律未知，不无证推定良好。
 *
 * Notes
 * -----
 * 单个 `last_is_success` 布尔无法区分「连续多次失败」，故偏离暂只此一档；加重（bad）留待有
 * 失败计数时再分。
 */
export function integrityOf(item: AccountDashboardItem): IntegrityStatus {
  if (item.last_is_success === 1) return { integrity: 'aligned', text: '已按策略到位' }
  if (item.last_is_success === 0) return { integrity: 'off', text: '上次未到位 · 需要看看' }
  // last_is_success == null：区分「从未执行」与「有记录但结果缺失」，两者皆未知。
  if (item.last_exec_at == null) return { integrity: 'unknown', text: '尚无执行记录 · 先跑一次对账' }
  return { integrity: 'unknown', text: '执行结果未知 · 需要看看' }
}

/**
 * 从仪表盘项派生**档位**（模式轴）。
 *
 * 纯看 `is_started`。模式天生中性、是上下文——它该落在账户名旁的安静 chip，
 * 绝不占头条把风险（见 :func:`integrityOf`）挤走。
 */
export function gateOf(item: AccountDashboardItem): GateStatus {
  return item.is_started ? { gate: 'auto', label: '自动' } : { gate: 'paused', label: '已暂停' }
}

/** 在位性 × 档位 的四象限判词。 */
export interface StateVerdict {
  integrity: Integrity
  /** 头条主句。 */
  text: string
  /** 是否加重——仅「暂停且偏离」：偏了又关了自动纠偏、不会自愈。琥珀内用字重承载，不新增颜色。 */
  loud: boolean
}

/** 毛敞口 = Σ|持仓市值| / 总权益（>1 即杠杆）。position_weights 取前 12 大绝对市值，>12 只时略低估。 */
export function grossExposure(item: AccountDashboardItem): number {
  if (!(item.total_asset > 0)) return 0
  const gross = item.position_weights.reduce((sum, w) => sum + Math.abs(w), 0)
  return gross / item.total_asset
}

/**
 * 由在位性 × 档位 × 敞口合成判词与音量.
 *
 * 模式给风险改台词、敞口再分档：`暂停+偏离` 自动纠偏已关、不会自愈（最重）；`自动+偏离且高杠杆`
 * 会自愈但敞口大（也加重）；`自动+偏离且低敞口`（较轻）。在位 / 未知与档位无关，保持中性安静、
 * 沿用 :func:`integrityOf` 的措辞。取乐观档位时，先把 `is_started` override 进 `item` 再传入。

 * Parameters
 * ----------
 * item : AccountDashboardItem
 *     仪表盘项（`is_started` 可为乐观覆盖值）。

 * Returns
 * -------
 * StateVerdict
 *     判词主句与音量；`loud` 在「暂停且偏离」或「偏离且高杠杆」为真。
 */
export function stateVerdict(item: AccountDashboardItem): StateVerdict {
  const { integrity, text } = integrityOf(item)
  if (integrity !== 'off') return { integrity, text, loud: false }
  // 音量分档：暂停+偏离＝不会自愈（最重）；自动+偏离但高杠杆＝会自愈但高敞口、也加重；自动+低敞口＝较轻。
  if (gateOf(item).gate === 'paused') return { integrity, text: '上次未到位 · 自动纠偏已关，需手动', loud: true }
  if (grossExposure(item) > 1) return { integrity, text: '上次未到位 · 将自动重试 · 敞口偏高', loud: true }
  return { integrity, text: '上次未到位 · 将自动重试', loud: false }
}

/** 敞口条分段颜色：按序渐隐的品牌蓝。 */
export function barColor(i: number): string {
  return `rgba(37,99,235,${Math.max(0.22, 0.85 - i * 0.06).toFixed(2)})`
}

/** 金额格式化：按数量级选精度，保留千分位与等宽。 */
export function formatMoney(v: number): string {
  const abs = Math.abs(v)
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : 4
  return v.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** 持仓一句话描述。 */
export function holdingText(count: number, weights: number[]): string {
  if (count === 0) return '空仓'
  const max = weights.length ? Math.max(...weights.map(Math.abs)) : 0
  const total = weights.reduce((s, w) => s + Math.abs(w), 0) || 1
  return `持有 ${count} 只 · 最大 ${((max / total) * 100).toFixed(0)}%`
}

/**
 * 持仓 vs 目标的收敛判定（原子详情用）。
 *
 * `positions` 取自最近执行记录快照，`target` 取自 latest_weights。仅当两边都
 * 拿得到时才给结论；否则返回 null（交给上层降级）。
 */
/**
 * 从执行记录中「最近一条带账户资产快照」的记录取持仓列表。
 *
 * 回溯扫描而非只看 `records[0]`：最新一条执行可能是「终止/失败」且不带 `account_assets`
 * 快照，只看最新会把「实际持有仓位」误判为空仓，并据此给出「买入建仓」的错误调仓建议
 * （与后端 dashboard 的 `holdings_count` 相矛盾——后者同样回溯扫描最近若干条取第一条带快照的）。
 * 这里对齐该口径：跳过无快照的记录，取最近一条有快照者；全都没有时返回空数组，交由上层
 * 结合 `holdings_count` 降级为「持仓待刷新」而非坐实「空仓」。
 */
export function positionsOf(records: ExecuteRecord[]): Position[] {
  for (const rec of records) {
    const positions = rec?.raw_result?.account_assets?.positions
    if (Array.isArray(positions)) return positions
  }
  return []
}

/** 调仓阈值：|当前−目标| 小于此百分点视为「到位」。 */
export const REBALANCE_THRESHOLD = 0.5

/** 单只调仓动作分类。 */
export type RebalanceAction =
  | 'aligned' // 到位
  | 'increase' // 同向加仓
  | 'reduce' // 同向减仓
  | 'open' // 建仓（从空到有）
  | 'close' // 清仓（到空）
  | 'flip' // 多空翻转

/** 单只调仓行：当前/目标均为「带符号、占权益」的百分数。 */
export interface RebalanceRow {
  symbol: string
  cur: number
  tgt: number
  /** ``cur - tgt``；>0 超配待卖，<0 欠配待买。 */
  delta: number
  amount: number
  side: 'buy' | 'sell' | 'none'
  action: RebalanceAction
}

/** 整账户调仓计划与汇总。 */
export interface RebalancePlan {
  rows: RebalanceRow[]
  /** 待调整（非到位）品种数。 */
  off: number
  buys: number
  sells: number
  flips: number
  /** 当前净敞口 Σcur（%）。 */
  netExposure: number
  /** 当前毛敞口 Σ|cur|（%）。 */
  grossExposure: number
  /** 目标净敞口 Σtgt（%）。 */
  targetNet: number
}

/** 判断持仓方向是否为空头（容错中英文写法）。 */
function isShort(direction: unknown): boolean {
  return typeof direction === 'string' && (direction.includes('空') || direction.toLowerCase().includes('short'))
}

/** 由单只的当前/目标（带符号）派生动作分类。 */
function classifyAction(cur: number, tgt: number, delta: number): RebalanceAction {
  if (Math.abs(delta) <= REBALANCE_THRESHOLD) return 'aligned'
  if (Math.abs(cur) < 1e-6) return 'open'
  if (Math.abs(tgt) < 1e-6) return 'close'
  if (Math.sign(cur) !== Math.sign(tgt)) return 'flip'
  return Math.abs(cur) < Math.abs(tgt) ? 'increase' : 'reduce'
}

/**
 * 合并当前持仓与目标权重为逐只调仓计划.

 * 与旧实现的本质区别（口径纠正）：当前权重按 ``direction`` 带上多空符号、并以
 * ``equity``（总权益）为分母，与目标（策略净权重）同口径；``delta = cur - tgt``
 * 即真实「要成交多少」，据此判定买/卖方向与动作类别（做空品种的方向不再算反）。

 * Parameters
 * ----------
 * positions : Position[]
 *     当前持仓（``market_value`` 为幅度，``direction`` 表方向）。
 * target : LatestWeights
 *     目标权重（分数，可为负=做空）。
 * equity : number
 *     账户总权益，作为归一分母；``<= 0`` 时当前权重按 0 处理。

 * Returns
 * -------
 * RebalancePlan
 *     逐只行（按 ``|delta|`` 降序）与账户级汇总。
 */
export function rebalancePlan(positions: Position[], target: LatestWeights, equity: number): RebalancePlan {
  const curMv = new Map<string, number>()
  for (const p of positions) {
    if (typeof p.symbol !== 'string') continue
    const mag = Math.abs(Number(p.market_value) || 0)
    const signed = isShort(p.direction) ? -mag : mag
    curMv.set(p.symbol, (curMv.get(p.symbol) ?? 0) + signed)
  }
  const base = equity > 0 ? equity : 0
  const syms = new Set<string>([...curMv.keys(), ...Object.keys(target)])
  const rows: RebalanceRow[] = []
  for (const s of syms) {
    const cur = base > 0 ? ((curMv.get(s) ?? 0) / base) * 100 : 0
    const tgt = (target[s] ?? 0) * 100
    if (Math.abs(cur) < 1e-6 && Math.abs(tgt) < 1e-6) continue
    const delta = +(cur - tgt).toFixed(2)
    const action = classifyAction(cur, tgt, delta)
    const side = action === 'aligned' ? 'none' : delta < 0 ? 'buy' : 'sell'
    rows.push({ symbol: s, cur, tgt, delta, amount: Math.abs(delta), side, action })
  }
  rows.sort((a, b) => b.amount - a.amount)
  return {
    rows,
    off: rows.filter((r) => r.action !== 'aligned').length,
    buys: rows.filter((r) => r.side === 'buy').length,
    sells: rows.filter((r) => r.side === 'sell').length,
    flips: rows.filter((r) => r.action === 'flip').length,
    netExposure: rows.reduce((sum, r) => sum + r.cur, 0),
    grossExposure: rows.reduce((sum, r) => sum + Math.abs(r.cur), 0),
    targetNet: rows.reduce((sum, r) => sum + r.tgt, 0),
  }
}

/**
 * 账户「是否调仓到位」的一句话汇总（供仪表盘卡片用）.

 * 与持仓明细抽屉共用 :func:`rebalancePlan` 的幅度口径，两处数字始终一致。
 */
export function convergence(
  positions: Position[],
  target: LatestWeights,
  equity: number,
): { level: StatusLevel; text: string; offCount: number } {
  const plan = rebalancePlan(positions, target, equity)
  if (plan.rows.length === 0) return { level: 'ok', text: '空仓 · 与目标一致', offCount: 0 }
  if (plan.off === 0) return { level: 'ok', text: '已调仓到位', offCount: 0 }
  return { level: 'warn', text: `${plan.off} 个品种与目标背离`, offCount: plan.off }
}
