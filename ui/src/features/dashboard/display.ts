/** 仪表盘展示层常量与小工具。 */
import type { Integrity, StatusLevel } from '@/lib/derive'
import type { TradeChannel } from '@/types/api'
import { getChannelDescriptor } from '@/stores/channels'

/** 状态图标。 */
export const STATUS_ICON: Record<StatusLevel, string> = {
  ok: '✓',
  warn: '⚠',
  bad: '✕',
  run: '⟳',
}

/**
 * 状态对应的文字色类。
 *
 * 刻意让「成败」语义**离开红绿**：红绿在本系统专供行情涨跌（红涨绿跌），
 * 若状态也用红绿，红=涨(好)又=失败(坏)、绿=成功(好)又=跌(坏)，颜色即失去效价。
 * 故：正常=中性(安静即好)、注意与失败=同一琥珀色相，失败靠 ✕ 图标+字重/填充拉严重度。
 */
export const STATUS_TEXT_CLASS: Record<StatusLevel, string> = {
  ok: 'text-ink-1',
  warn: 'text-warn',
  bad: 'text-warn',
  run: 'text-accent',
}

/** 在位性（风险轴）图标：在位＝✓、偏离＝⚠、未知＝–（无判词，安静）。 */
export const INTEGRITY_ICON: Record<Integrity, string> = {
  aligned: '✓',
  off: '⚠',
  unknown: '–',
}

/**
 * 在位性文字色类（严守成败离红绿）。
 *
 * 在位＝中性（安静即好，不表扬）、偏离＝琥珀（注意/失败）、未知＝更弱中性（缺证据、不报警）。
 * 颜色只花在「偏离」上；在位与未知都不烧注意力预算。
 */
export const INTEGRITY_TEXT_CLASS: Record<Integrity, string> = {
  aligned: 'text-ink-1',
  off: 'text-warn',
  unknown: 'text-ink-3',
}

/** 舰队排序权重：偏离在前、未知居中、在位垫后。 */
export const INTEGRITY_ORDER: Record<Integrity, number> = {
  off: 0,
  unknown: 1,
  aligned: 2,
}

/** 渠道简称（胶囊用）。 */
export const CHANNEL_TAG: Record<TradeChannel, string> = {
  ctp: 'CTP',
  gm: '掘金',
}

/** 渠道 + 市场的完整描述（hero 胶囊用）。 */
export function channelLabel(channel: TradeChannel, market: string): string {
  const base = getChannelDescriptor(channel)?.label ?? CHANNEL_TAG[channel] ?? channel
  return market ? `${base} · ${market}` : base
}
