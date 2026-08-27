import { describe, expect, it } from 'bun:test'

import { accountAssetTerms, positionValueLabelOf } from '@/features/dashboard/display'

describe('accountAssetTerms', () => {
  it('uses asset terminology for the GM stock channel', () => {
    expect(accountAssetTerms('gm')).toEqual({
      fullLabel: '总资产',
      shortLabel: '资产',
      pointLabel: '资产点',
      ratioLabel: '占总资产',
    })
  })

  it.each(['ctp', 'tq', 'plugin-channel', 'another-plugin', undefined])(
    'uses equity terminology for %s',
    (channel) => {
      expect(accountAssetTerms(channel)).toEqual({
        fullLabel: '账户权益',
        shortLabel: '权益',
        pointLabel: '权益点',
        ratioLabel: '占权益',
      })
    },
  )
})

describe('positionValueLabelOf', () => {
  it('使用渠道声明的持仓金额称谓', () => {
    expect(positionValueLabelOf({ position_value_label: '货值' })).toBe('货值')
    expect(positionValueLabelOf({ position_value_label: '名义价值' })).toBe('名义价值')
  })

  it('兼容未携带新字段的旧服务', () => {
    expect(positionValueLabelOf(undefined)).toBe('市值')
    expect(positionValueLabelOf({})).toBe('市值')
  })
})
