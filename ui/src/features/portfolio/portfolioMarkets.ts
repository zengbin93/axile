import type { ChannelCapability } from '@/types/api'

export interface PortfolioMarketOption {
  value: string
  label: string
  exampleSymbols: string[]
}

/** 按渠道注册顺序生成去重后的组合市场目录。 */
export function portfolioMarketOptions(channels: ChannelCapability[]): PortfolioMarketOption[] {
  const seen = new Set<string>()
  const options: PortfolioMarketOption[] = []
  for (const channel of channels) {
    if (seen.has(channel.market)) continue
    seen.add(channel.market)
    options.push({
      value: channel.market,
      label: channel.portfolio.market_label,
      exampleSymbols: channel.portfolio.example_symbols,
    })
  }
  return options
}

/** 根据渠道提供的标的生成最小可运行组合函数。 */
export function portfolioTemplate(option: PortfolioMarketOption): string {
  const weight = 1 / option.exampleSymbols.length
  const entries = option.exampleSymbols.map((symbol) => `${JSON.stringify(symbol)}: ${Number(weight.toFixed(6))}`)
  return `def calculate_portfolio(context):\n    # 返回 {品种: 目标权重}\n    return {${entries.join(', ')}}`
}
