import type { ChannelCapability } from '@/types/api'

export interface PortfolioMarketOption {
  value: string
  label: string
  exampleSymbols: string[]
}

export interface PortfolioTemplateDraft {
  market: string
  customCode: string
  templateMarket: string | null
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

/** 切换市场；仅空代码或未修改的系统模板会被自动替换。 */
export function selectPortfolioMarket(
  draft: PortfolioTemplateDraft,
  nextMarket: PortfolioMarketOption,
  options: PortfolioMarketOption[],
): PortfolioTemplateDraft {
  const previous = options.find((option) => option.value === draft.market)
  const previousTemplate = previous ? portfolioTemplate(previous) : null
  const replaceTemplate =
    !draft.customCode.trim() ||
    (draft.templateMarket === draft.market && previousTemplate !== null && draft.customCode === previousTemplate)

  return replaceTemplate
    ? {
        market: nextMarket.value,
        customCode: portfolioTemplate(nextMarket),
        templateMarket: nextMarket.value,
      }
    : { ...draft, market: nextMarket.value }
}
