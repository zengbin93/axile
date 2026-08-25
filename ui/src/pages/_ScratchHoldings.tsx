import { Card } from '@/components/ui/Card'
import { HoldingsView } from '@/features/account/HoldingsView'
import type { Position } from '@/types/api'

/** 临时视觉验证页（截图后删除）：加/减/建/翻 四态混合，验证「亮=加 虚=减」明度编码。 */
const EQUITY = 5151
const positions: Position[] = [
  { symbol: 'ag2612', market_value: 2678, direction: '空头' }, // 空 -52% → -17.2% 减
  { symbol: 'rb2610', market_value: 711, direction: '多头' }, // 多 +13.8% → +40.8% 加
  { symbol: 'm2609', market_value: 1339, direction: '多头' }, // 多 +26% → +8.8% 减
  { symbol: 'cu2610', market_value: 515, direction: '多头' }, // 多 +10% → -8% 翻向
  { symbol: 'au2612', market_value: 206, direction: '空头' }, // 空 -4% → -1.2% 减
]
const target = {
  ag2612: -0.172,
  rb2610: 0.408,
  m2609: 0.088,
  SR609: 0.2, // 无持仓 → 建仓（全新，全亮）
  cu2610: -0.08,
  au2612: -0.012,
}

export function ScratchHoldings() {
  return (
    <section className="mx-auto w-full max-w-[860px] px-6 pt-8 pb-16">
      <div className="mt-3 text-[13px] text-ink-3">持仓明细</div>
      <div className="text-[18px] font-[640]">testnet</div>
      <Card className="mt-4 px-6 py-5">
        <HoldingsView positions={positions} target={target} equity={EQUITY} currency="CNY" assetLabel="权益" />
      </Card>
    </section>
  )
}
