import { describe, expect, it } from 'bun:test'

import type { ChannelCapability } from '@/types/api'
import {
  portfolioMarketOptions,
  portfolioTemplate,
  selectPortfolioMarket,
} from './portfolioMarkets'

function channel(
  market: string,
  label: string,
  symbols: string[],
  available = true,
): ChannelCapability {
  return {
    channel: `${market}-${label}`,
    label,
    description: label,
    icon: 'landmark',
    available,
    missing_packages: available ? [] : ['vendor-sdk'],
    install_extra: null,
    market,
    schedule: { kind: 'continuous' },
    calendar: null,
    currency: 'CNY',
    units: {
      quantity_kind: 'custom',
      quantity_label: '',
      quantity_max_decimals: 6,
      price_label: '',
      notional_label: '',
    },
    ui: {
      account_connect_lead: '',
      leverage_title: '杠杆',
      leverage_note: '',
      long_leverage_label: '做多杠杆',
      short_leverage_label: '做空杠杆',
      show_short_leverage: true,
    },
    defaults: {
      long_leverage: 1,
      short_leverage: 1,
      execution_timeout: 60,
      trade_algorithm: { method: 'DEMO', params: {} },
      empty_positions_algorithm: null,
    },
    leverage: { min: 0, max: 10, step: 1 },
    account_form: { fields: [], notices: [] },
    portfolio: { market_label: label, example_symbols: symbols },
  }
}

describe('portfolio market presets', () => {
  const futuresChannel = channel('ctp', '期货', ['rb2610', 'ag2612'])
  const stocksChannel = channel('ashare', 'A股', ['600000.SH', '000001.SZ'])
  const options = portfolioMarketOptions([futuresChannel, stocksChannel])
  const futures = options[0]!
  const stocks = options[1]!

  it('deduplicates channels in stable market order', () => {
    const duplicate = channel('ctp', '另一个期货渠道', ['cu2610'])
    expect(portfolioMarketOptions([futuresChannel, duplicate, stocksChannel])).toEqual([
      { value: 'ctp', label: '期货', exampleSymbols: ['rb2610', 'ag2612'] },
      { value: 'ashare', label: 'A股', exampleSymbols: ['600000.SH', '000001.SZ'] },
    ])
  })

  it('adds a market only when its channel plugin is registered', () => {
    expect(portfolioMarketOptions([futuresChannel, stocksChannel]).map((option) => option.value)).toEqual([
      'ctp',
      'ashare',
    ])
    const external = channel('external-market', '外部市场', ['PLUGIN-SYMBOL'])
    expect(portfolioMarketOptions([futuresChannel, stocksChannel, external]).map((option) => option.value)).toEqual([
      'ctp',
      'ashare',
      'external-market',
    ])
  })

  it('keeps registered markets whose optional dependencies are unavailable', () => {
    const unavailable = channel('external', '外部市场', ['EXT-1'], false)
    expect(portfolioMarketOptions([unavailable])).toEqual([
      { value: 'external', label: '外部市场', exampleSymbols: ['EXT-1'] },
    ])
  })

  it('replaces an untouched system template when the market changes', () => {
    const current = portfolioTemplate(futures)
    expect(
      selectPortfolioMarket(
        { market: 'ctp', customCode: current, templateMarket: 'ctp' },
        stocks,
        [futures, stocks],
      ),
    ).toEqual({
      market: 'ashare',
      customCode: portfolioTemplate(stocks),
      templateMarket: 'ashare',
    })
  })

  it('initializes an empty draft from the first registered market when its default is absent', () => {
    expect(
      selectPortfolioMarket(
        { market: 'missing-default', customCode: '', templateMarket: null },
        futures,
        [futures, stocks],
      ),
    ).toEqual({
      market: 'ctp',
      customCode: portfolioTemplate(futures),
      templateMarket: 'ctp',
    })
  })

  it('preserves user code when the market changes', () => {
    const customCode = 'def calculate_portfolio(context):\n    return {}'
    expect(
      selectPortfolioMarket(
        { market: 'ctp', customCode, templateMarket: 'ctp' },
        stocks,
        [futures, stocks],
      ),
    ).toEqual({ market: 'ashare', customCode, templateMarket: 'ctp' })
  })

  it('supports explicitly replacing preserved code with the selected market template', () => {
    const preserved = selectPortfolioMarket(
      {
        market: 'ctp',
        customCode: 'def calculate_portfolio(context):\n    return {}',
        templateMarket: 'ctp',
      },
      stocks,
      [futures, stocks],
    )

    expect({
      ...preserved,
      customCode: portfolioTemplate(stocks),
      templateMarket: stocks.value,
    }).toEqual({
      market: 'ashare',
      customCode: portfolioTemplate(stocks),
      templateMarket: 'ashare',
    })
  })
})
