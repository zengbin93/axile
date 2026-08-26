import { describe, expect, it } from 'bun:test'

import { appendUniqueSymbols, splitSymbols } from './symbolTags'

describe('splitSymbols', () => {
  it('支持 Enter、逗号、中文逗号、空格与批量粘贴', () => {
    expect(splitSymbols('600000.SH, 000001.SZ，AAPL\nMSFT')).toEqual([
      '600000.SH',
      '000001.SZ',
      'AAPL',
      'MSFT',
    ])
  })

  it('忽略空白并保留用户输入的大小写', () => {
    expect(splitSymbols('  600000.SH ,,\n AAPL  ')).toEqual(['600000.SH', 'AAPL'])
  })
})

describe('appendUniqueSymbols', () => {
  it('按原顺序追加并去重', () => {
    expect(appendUniqueSymbols(['600000.SH'], ['AAPL', '600000.SH', 'AAPL'])).toEqual([
      '600000.SH',
      'AAPL',
    ])
  })
})
