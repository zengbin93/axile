import { useId, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { displayCurrencyUnit, fmtMoney } from '@/lib/format'
import {
  quantityText,
  sizingNumber,
  sizingReasonText,
  targetQuantityText,
  weightText,
} from '@/features/account/sizingEvidenceModel'
import type { TargetSizingRow } from '@/types/api'

function formulaRows(row: TargetSizingRow, quantityLabel: string, currency: string): string[] {
  const rows: string[] = []
  const currencyLabel = displayCurrencyUnit(currency)
  if (row.strategy_weight != null && row.account_weight != null) {
    const multiplier = row.account_multiplier
    rows.push(
      multiplier != null
        ? `策略 ${weightText(row.strategy_weight)} × 账户乘数 ${sizingNumber(multiplier, 4)} = 账户 ${weightText(row.account_weight)}`
        : `策略 ${weightText(row.strategy_weight)} → 账户 ${weightText(row.account_weight)}`,
    )
  }
  if (row.equity != null && row.account_weight != null && row.target_notional != null) {
    rows.push(
      `权益 ${fmtMoney(row.equity)} × ${sizingNumber(Math.abs(row.account_weight) * 100, 2)}% = 目标名义 ${fmtMoney(row.target_notional)}${currencyLabel ? ` ${currencyLabel}` : ''}`,
    )
  }
  if (row.reference_price != null && row.unit_notional != null) {
    rows.push(
      row.unit_multiplier != null && Math.abs(row.unit_multiplier - 1) > 1e-9
        ? `价格 ${sizingNumber(row.reference_price, 6)} × 合约乘数 ${sizingNumber(row.unit_multiplier)} = 每${quantityLabel || '单位'} ${fmtMoney(row.unit_notional)}${currencyLabel ? ` ${currencyLabel}` : ''}`
        : `价格 ${sizingNumber(row.reference_price, 6)}${currencyLabel ? ` ${currencyLabel}` : ''}/${quantityLabel || '单位'}`,
    )
  }
  if (row.raw_quantity != null) {
    rows.push(`未取整目标 ${quantityText(row.raw_quantity, quantityLabel)}`)
  }
  if (row.target_quantity != null) {
    rows.push(`${sizingReasonText(row, quantityLabel)} → 可执行目标 ${targetQuantityText(row.target_quantity, quantityLabel)}`)
  }
  return rows
}

export function SizingEvidence({
  row,
  quantityLabel = '',
  currency = '',
}: {
  row: TargetSizingRow
  quantityLabel?: string
  currency?: string
}) {
  const [open, setOpen] = useState(false)
  const detailId = useId()
  const reason = sizingReasonText(row, quantityLabel)
  const summary = `${weightText(row.account_weight)} → ${targetQuantityText(row.target_quantity, quantityLabel)} · ${reason}`
  const formulas = formulaRows(row, quantityLabel, currency)

  return (
    <div>
      <button
        type="button"
        className="group flex min-h-8 w-full items-center gap-2 text-left"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="num min-w-0 flex-1 text-[13.5px] text-ink-2">{summary}</span>
        <ChevronDown
          size={15}
          aria-hidden
          className={`flex-none text-ink-3 transition-transform duration-200 motion-reduce:transition-none ${open ? 'rotate-180' : ''}`}
        />
      </button>
      <div
        inert={!open}
        className={`grid transition-[grid-template-rows] duration-200 motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div id={detailId} className="min-h-0 overflow-hidden">
          <div className="num border-l border-line py-1.5 pl-3 text-[12.5px] leading-5 text-ink-3">
            {formulas.map((formula) => <div key={formula}>{formula}</div>)}
          </div>
        </div>
      </div>
    </div>
  )
}
