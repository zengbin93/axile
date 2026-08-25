import { describe, expect, it } from 'bun:test'

import { appendUniqueSymbols, splitSymbols } from './symbolTags'

describe('splitSymbols', () => {
  it('支持 Enter、逗号、中文逗号、空格与批量粘贴', () => {
    expect(splitSymbols('IF2609, ag2612，CF601\ncu2609')).toEqual([
      'IF2609',
      'ag2612',
      'CF601',
      'cu2609',
    ])
  })

  it('忽略空白并保留用户输入的大小写', () => {
    expect(splitSymbols('  if2609 ,,\n ag2612  ')).toEqual(['if2609', 'ag2612'])
  })
})

describe('appendUniqueSymbols', () => {
  it('按原顺序追加并去重', () => {
    expect(appendUniqueSymbols(['IF2609'], ['ag2612', 'IF2609', 'ag2612'])).toEqual([
      'IF2609',
      'ag2612',
    ])
  })
})
