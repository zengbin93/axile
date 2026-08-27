import { rebalancePlan, type RebalanceRow } from '@/lib/derive'
import { OverflowText } from '@/components/ui/OverflowText'
import { displayCurrencyUnit, fmtMoney, signedPct, withCurrency } from '@/lib/format'
import type { LatestWeights, Position } from '@/types/api'

/**
 * 仅占比的持仓标签：身份靠外层「当前/目标」词说清，这里只出「方向+占比」.

 * ``|pct| < 0.05`` 记为「空仓」；否则方向（多/空）+ 一位小数百分比。市值不在标尺出
 * （改由头部权益与右侧成交承载），标尺只讲「当前↔目标」的占比变化。
 */
function pctLabel(pct: number): string {
  if (Math.abs(pct) < 0.05) return '空仓'
  return `${pct > 0 ? '多' : '空'}${Math.abs(pct).toFixed(1)}%`
}

/** 方向着色（红涨绿跌）：多头=up(红)、空头=down(绿)、空仓=中性 ink-1。 */
function dirCls(pct: number): string {
  if (Math.abs(pct) < 0.05) return 'text-ink-1'
  return pct > 0 ? 'text-up' : 'text-down'
}

/** open/close/flip 三类值得单列的动作给一枚小标签，其余不加噪。翻向加 warn 底衬（与顶栏偏离胶囊同族），10px 裸色字太浅。 */
const ACTION_TAG: Partial<Record<RebalanceRow['action'], { text: string; cls: string }>> = {
  open: { text: '建仓', cls: 'text-ink-3' },
  close: { text: '清仓', cls: 'text-ink-3' },
  flip: { text: '翻向', cls: 'inline-block rounded bg-warn-tint px-1 py-px font-medium text-warn' },
}

/** 有符号值在轴上的横向位置（%）：0 居中，±scale 落在 6%/94%（留边防裁切）。 */
function axisX(v: number, scale: number): number {
  return scale > 0 ? 50 + (v / scale) * 44 : 50
}

/**
 * 零锚有符号持仓标尺（B 版：一行「当前→目标」变化句 + 条）.
 *
 * 轴 = 空(左) ← 0 → 多(右)，零线固定、全表同尺（``scale`` 取 |当前|、|目标| 的全表最
 * 大值）。**「当前 空52.0% → 目标 空17.2%」一行变化句压在条上方、左对齐固定**——把身
 * 份直接写在数字上（新人不必回读表头凡例判断哪个是当前/目标），也不再随值横向漂移。
 * 条分两段：深色段 ``[0→核心(min)]`` 是稳住不动的仓、浅色(mid)段 ``[核心→外沿(max)]`` 是
 * 要动的量 ``|Δ|``。变化句里的数字按**方向着色**：**多头=红(涨)、空头=绿(跌)**——「红涨绿
 * 跌」，复用 up/down token（做多=看涨、做空=看跌，与行情语义同族）。空仓中性；翻向那行自然
 * 「红→绿」把反转也说清。到位时变化句退成单值。
 */
function Ruler({ row, scale }: { row: RebalanceRow; scale: number }) {
  const zero = axisX(0, scale)
  const xCur = axisX(row.cur, scale)
  const xTgt = axisX(row.tgt, scale)
  const flip = row.action === 'flip'
  const aligned = row.action === 'aligned'
  // 色相 = 方向：多头蓝(accent)、空头紫(short)；翻向横跨零线走 warn 橙。方向取非零那侧
  // 符号（建仓看目标、清仓看当前，同向两者同号）。
  // 棒中性单色（方向已交给红绿数字 + 零线左右位置，棒不再重复编方向）。翻向走 warn。
  const deepColor = flip ? 'bg-warn' : 'bg-accent'
  // 浅色段用实心「中间档」token（accent-mid/warn-mid），非透明——厚条上不发虚、与深色段同族。
  const lightColor = flip ? 'bg-warn-mid' : 'bg-accent-mid'

  let deep: { lo: number; hi: number }
  let light: { lo: number; hi: number }
  if (flip) {
    // 翻向：深=新向目标 [0→目标]、浅=待平旧仓 [0→当前]，分居零线两侧。
    deep = { lo: Math.min(zero, xTgt), hi: Math.max(zero, xTgt) }
    light = { lo: Math.min(zero, xCur), hi: Math.max(zero, xCur) }
  } else {
    // 同向：深=核心 [0→近端(min)]、浅=要动的量 [近端→远端(max)]，深浅交界即目标。
    const near = Math.abs(row.cur) <= Math.abs(row.tgt) ? xCur : xTgt
    const far = Math.abs(row.cur) <= Math.abs(row.tgt) ? xTgt : xCur
    deep = { lo: Math.min(zero, near), hi: Math.max(zero, near) }
    light = { lo: Math.min(near, far), hi: Math.max(near, far) }
  }

  return (
    <div className="flex-1">
      {/* 变化句：身份贴在数字上（当前→目标），居中对齐表头零轴、不随值漂移 */}
      <div className="num mb-1.5 whitespace-nowrap text-center text-[12px] leading-none">
        <span className="text-ink-3">当前 </span>
        <span className={`font-semibold ${dirCls(row.cur)}`}>{pctLabel(row.cur)}</span>
        {!aligned && (
          <>
            <span className="text-ink-3"> → 目标 </span>
            <span className={`font-medium ${dirCls(row.tgt)}`}>{pctLabel(row.tgt)}</span>
          </>
        )}
      </div>
      {/* 条：更粗实心数据条 + 全高零线。overflow-hidden 让端角随轨道微圆、深浅交界处保持 crisp。 */}
      <div className="relative h-4">
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-ink-1/10" />
        <div className="absolute inset-x-0 top-1/2 h-3 -translate-y-1/2 overflow-hidden rounded-sm bg-fill">
          {light.hi - light.lo > 0.1 && (
            <div
              className={`absolute inset-y-0 ${lightColor}`}
              style={{ left: `${light.lo}%`, width: `${light.hi - light.lo}%` }}
            />
          )}
          {deep.hi - deep.lo > 0.1 && (
            <div
              className={`absolute inset-y-0 ${deepColor}`}
              style={{ left: `${deep.lo}%`, width: `${deep.hi - deep.lo}%` }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * 持仓 vs 目标的逐只调仓视图（融合标签的零锚标尺）。
 *
 * 纯展示：给定当前持仓、目标权重与账户权益，用 :func:`rebalancePlan` 派生逐只买卖
 * 动作并渲染。当前/目标的「市值·占比」钉在标尺上（市值 = 占比 × 权益，与派生同口
 * 径），成交留右侧可扫的行动列，权益锚在头部。抽屉与 ``/accounts/:id/holdings`` 路
 * 由页共用本视图。
 */
export function HoldingsView({
  positions,
  target,
  equity,
  currency = '',
  assetLabel,
  quantities = null,
}: {
  positions: Position[]
  target: LatestWeights
  /** 账户总权益，作为当前权重的归一分母、也作市值换算基数。 */
  equity: number
  /** 计价货币代码，在头部权益处「说一次」立单位锚；拿不到时不显示。 */
  currency?: string
  /** 按账户渠道确定的行内资金名称。 */
  assetLabel: string
  /** 服务端量化后的目标数量；缺省时按权重阈值回退。 */
  quantities?: LatestWeights | null
}) {
  const plan = rebalancePlan(positions, target, equity, quantities)
  // 标尺同尺：以「当前/目标」绝对值的全表最大为满量程（不再用 |Δ|）。
  const scale = plan.rows.reduce((m, r) => Math.max(m, Math.abs(r.cur), Math.abs(r.tgt)), 0)
  // 当前实际持仓只数（与 posLabel 的「空仓」阈值一致），供顶部一句话汇总当前状态。
  const heldCount = plan.rows.filter((r) => Math.abs(r.cur) >= 0.05).length

  if (plan.rows.length === 0) {
    return <p className="text-[15px] text-ink-2">当前空仓，且无目标持仓。</p>
  }

  return (
    <>
      <div className="mb-1 text-[14px] text-ink-2">
        {plan.rows.length} 只 · {plan.rows.length - plan.off} 到位
        {plan.off > 0 && <span className="font-semibold text-warn"> · {plan.off} 待调整</span>}
      </div>
      <div className="num mb-3 text-[13px] text-ink-3">
        <span className="text-ink-2">当前 {heldCount === 0 ? '空仓' : `持有 ${heldCount} 只`}</span>
        {equity > 0 && (
          <>
            {' · '}{assetLabel} {fmtMoney(equity)}
            {currency && <span className="text-ink-2"> {displayCurrencyUnit(currency)}</span>}
          </>
        )}
        {' · '}净敞口 {signedPct(plan.netExposure)} → 目标 {signedPct(plan.targetNet)}
        {plan.off > 0 && (
          <>
            {' · '}待买 {plan.buys} · 待卖 {plan.sells}
            {plan.flips > 0 && <span className="font-medium text-warn"> · 翻向 {plan.flips}</span>}
          </>
        )}
      </div>

      <div className="flex items-center gap-4 py-1.5 text-[12px] text-ink-3">
        <span className="w-28 flex-none">代码</span>
        <span className="flex-1 text-center">空 ◄ 0 ► 多</span>
        <span className="w-32 flex-none text-right">成交</span>
      </div>

      {plan.rows.map((r) => {
        const aligned = r.action === 'aligned'
        const tag = ACTION_TAG[r.action]
        return (
          <div
            key={r.symbol}
            className={`flex items-center gap-4 border-t border-line py-3 ${aligned ? 'opacity-55' : ''}`}
          >
            <div className="w-28 min-w-0 flex-none self-center">
              <OverflowText className="text-[14.5px] font-medium" text={r.symbol} />
            </div>
            <Ruler row={r} scale={scale} />
            <div className="w-32 flex-none self-center text-right">
              {aligned ? (
                <span className="text-[14px] text-ink-3">到位</span>
              ) : (
                <>
                  <div className="num text-[14px] font-semibold">
                    {r.side === 'buy' ? '买' : '卖'}{' '}
                    {equity > 0
                      ? withCurrency(fmtMoney((r.amount / 100) * equity), currency)
                      : `${r.amount.toFixed(1)}%`}
                    {equity > 0 && <span className="font-normal text-ink-3"> ({r.amount.toFixed(1)}%)</span>}
                  </div>
                  {tag && <div className={`text-[11px] ${tag.cls}`}>{tag.text}</div>}
                </>
              )}
            </div>
          </div>
        )
      })}
    </>
  )
}
