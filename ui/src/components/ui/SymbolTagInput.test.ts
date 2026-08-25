import { describe, expect, it } from 'bun:test'

import { appendUniqueSymbols, splitSymbols } from './symbolTags'

describe('splitSymbols', () => {
  it('支持 Enter、逗号、中文逗号、空格与批量粘贴', () => {
    expect(splitSymbols('BTCUSDT, ETHUSDT，SOLUSDT\nDOGEUSDT')).toEqual([
      'BTCUSDT',
      'ETHUSDT',
      'SOLUSDT',
      'DOGEUSDT',
    ])
  })

  it('忽略空白并保留用户输入的大小写', () => {
    expect(splitSymbols('  btcUSDT ,,\n ETHUSDT  ')).toEqual(['btcUSDT', 'ETHUSDT'])
  })
})

describe('appendUniqueSymbols', () => {
  it('按原顺序追加并去重', () => {
    expect(appendUniqueSymbols(['BTCUSDT'], ['ETHUSDT', 'BTCUSDT', 'ETHUSDT'])).toEqual([
      'BTCUSDT',
      'ETHUSDT',
    ])
  })
})
