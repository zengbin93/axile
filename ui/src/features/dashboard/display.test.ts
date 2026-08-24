import { describe, expect, it } from 'bun:test'

import { accountAssetTerms } from '@/features/dashboard/display'

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
