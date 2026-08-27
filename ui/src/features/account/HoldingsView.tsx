import { OverflowText } from '@/components/ui/OverflowText'
import { SizingEvidence } from '@/features/account/SizingEvidence'
import {
  isQuantizedZero,
  quantityText,
  sizingAvailabilityText,
  weightText,
} from '@/features/account/sizingEvidenceModel'
import { rebalancePlan } from '@/lib/derive'
import { displayCurrencyUnit, fmtMoney, signedPct } from '@/lib/format'
import type { LatestWeights, Position, TargetSizing } from '@/types/api'

const QTY_EPS = 1e-9

function isShort(direction: unknown): boolean {
  return typeof direction === 'string' && (direction.includes('空') || direction.toLowerCase().includes('short'))
}

function signedPositionQuantity(position: Position): number | null {
  const extra = position.extra
  if (extra && typeof extra === 'object' && 'net_position' in extra) {
    const net = Number((extra as { net_position?: unknown }).net_position)
    if (Number.isFinite(net)) return net
  }
  const volume = Number(position.volume)
  if (!Number.isFinite(volume)) return null
  return isShort(position.direction) ? -Math.abs(volume) : Math.abs(volume)
}

function currentQuantities(positions: Position[]): Map<string, number> {
  const result = new Map<string, number>()
  for (const position of positions) {
    if (typeof position.symbol !== 'string') continue
    const quantity = signedPositionQuantity(position)
    if (quantity == null) continue
    result.set(position.symbol, (result.get(position.symbol) ?? 0) + quantity)
  }
  return result
}

/** 安静的逐只目标链：策略/账户/可执行/实际四层事实按需展开。 */
export function HoldingsView({
  positions,
  target,
  equity,
  currency = '',
  assetLabel,
  quantities = null,
  sizing = null,
  quantityLabel = '',
}: {
  positions: Position[]
  target: LatestWeights
  equity: number
  currency?: string
  assetLabel: string
  quantities?: LatestWeights | null
  sizing?: TargetSizing | null
  quantityLabel?: string
}) {
  const plan = rebalancePlan(positions, target, equity, quantities)
  const actual = currentQuantities(positions)
  const available = sizing?.status === 'available'
  const quantizedAligned = plan.rows.filter((row) => {
    const evidence = sizing?.rows[row.symbol]
    return row.action === 'aligned' && isQuantizedZero(evidence)
  }).length
  const ordinaryAligned = plan.rows.length - plan.off - quantizedAligned
  const heldCount = positions.filter((position) => Math.abs(signedPositionQuantity(position) ?? 0) > QTY_EPS).length

  if (plan.rows.length === 0) {
    return <p className="text-[14px] text-ink-2">当前空仓，且无目标持仓。</p>
  }

  return (
    <>
      <div className="text-[14px] text-ink-2">
        {plan.rows.length} 只
        {ordinaryAligned > 0 && <span> · {ordinaryAligned} 到位</span>}
        {quantizedAligned > 0 && <span className="text-ink-3"> · {quantizedAligned} 量化为0</span>}
        {plan.off > 0 && <span className="font-medium text-warn"> · {plan.off} 待调整</span>}
      </div>
      <div className="num mt-1 mb-3 text-[12.5px] text-ink-3">
        当前 {heldCount === 0 ? '空仓' : `持有 ${heldCount} 只`}
        {equity > 0 && (
          <>
            {' · '}{assetLabel} {fmtMoney(equity)}
            {currency && ` ${displayCurrencyUnit(currency)}`}
          </>
        )}
        {' · '}净敞口 {signedPct(plan.netExposure)} → 目标 {signedPct(plan.targetNet)}
      </div>

      {!available && sizing && (
        <div className={`mb-2 text-[12.5px] ${sizing.status === 'pending_execution' ? 'text-ink-3' : 'text-warn'}`}>
          {sizingAvailabilityText(sizing.status)}
        </div>
      )}

      <div className="hidden grid-cols-[minmax(88px,0.7fr)_minmax(240px,2fr)_minmax(140px,0.9fr)] gap-4 py-1.5 text-[12px] text-ink-3 md:grid">
        <span>代码</span>
        <span>账户目标 → 可执行目标</span>
        <span className="text-right">实际持仓</span>
      </div>

      {plan.rows.map((row) => {
        const evidence = sizing?.rows[row.symbol]
        const current = actual.get(row.symbol) ?? 0
        const aligned = row.action === 'aligned'
        const quantized = isQuantizedZero(evidence)
        const actualText = available
          ? quantityText(current, quantityLabel)
          : weightText(row.cur / 100)
        const state = aligned ? (quantized ? '无需下单' : '到位') : '待调整'

        return (
          <div
            key={row.symbol}
            className="grid grid-cols-[minmax(82px,0.55fr)_minmax(0,1.8fr)] gap-x-3 border-t border-line py-2.5 md:grid-cols-[minmax(88px,0.7fr)_minmax(240px,2fr)_minmax(140px,0.9fr)] md:gap-x-4"
          >
            <div className="min-w-0 self-center">
              <OverflowText className="text-[14px] font-medium" text={row.symbol} />
            </div>
            <div className="min-w-0">
              {available && evidence ? (
                <SizingEvidence row={evidence} quantityLabel={quantityLabel} currency={currency} />
              ) : (
                <div className="num min-h-8 py-1.5 text-[13.5px] text-ink-2">
                  {weightText(target[row.symbol] ?? 0)} → 可执行数量—
                </div>
              )}
            </div>
            <div className="col-start-2 flex min-w-0 items-baseline justify-between gap-3 text-[12.5px] md:col-start-auto md:block md:self-center md:text-right">
              <span className="num text-ink-2">实际 {actualText}</span>
              <span className={aligned ? 'text-ink-3' : 'font-medium text-warn'}> · {state}</span>
            </div>
          </div>
        )
      })}
    </>
  )
}
