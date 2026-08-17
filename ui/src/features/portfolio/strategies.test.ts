import { describe, it, expect } from 'bun:test'

import type { DraftStrategy } from './diff'
import { parseNames, mergeImport, equalize, normalize, summary } from './strategies'

describe('parseNames', () => {
  it('按空白/逗号/分号/顿号任意组合切分', () => {
    expect(parseNames('a b\nc,d;e、f')).toEqual(['a', 'b', 'c', 'd', 'e', 'f'])
  })

  it('去除首尾空白并跳过空片段', () => {
    expect(parseNames('  a  ,, \n  b ')).toEqual(['a', 'b'])
  })

  it('输入内去重并保持首次出现顺序', () => {
    expect(parseNames('a b a c b')).toEqual(['a', 'b', 'c'])
  })

  it('空文本返回空列表', () => {
    expect(parseNames('   \n , 、 ')).toEqual([])
  })
})

describe('mergeImport', () => {
  const existing: DraftStrategy[] = [{ name: 'a', weight: 50 }]

  it('追加新名字为 weight 0，跳过已存在', () => {
    const r = mergeImport(existing, ['a', 'b', 'c'])
    expect(r.merged).toEqual([
      { name: 'a', weight: 50 },
      { name: 'b', weight: 0 },
      { name: 'c', weight: 0 },
    ])
    expect(r.added).toBe(2)
    expect(r.dup).toBe(1)
  })

  it('导入名内部重复也只并入一次', () => {
    const r = mergeImport([], ['x', 'x', 'y'])
    expect(r.merged.map((s) => s.name)).toEqual(['x', 'y'])
    expect(r.added).toBe(2)
    expect(r.dup).toBe(1)
  })

  it('不修改传入的 existing', () => {
    mergeImport(existing, ['b'])
    expect(existing).toEqual([{ name: 'a', weight: 50 }])
  })
})

describe('equalize', () => {
  it('平均分配并四舍五入到 0.1', () => {
    expect(equalize([{ name: 'a', weight: 0 }, { name: 'b', weight: 0 }, { name: 'c', weight: 0 }])).toEqual([
      { name: 'a', weight: 33.3 },
      { name: 'b', weight: 33.3 },
      { name: 'c', weight: 33.3 },
    ])
  })

  it('空列表原样返回', () => {
    expect(equalize([])).toEqual([])
  })
})

describe('normalize', () => {
  it('按比例缩放到合计 100', () => {
    const out = normalize([{ name: 'a', weight: 30 }, { name: 'b', weight: 10 }])
    expect(out).toEqual([{ name: 'a', weight: 75 }, { name: 'b', weight: 25 }])
  })

  it('合计为 0 时原样返回', () => {
    const rows = [{ name: 'a', weight: 0 }, { name: 'b', weight: 0 }]
    expect(normalize(rows)).toEqual(rows)
  })
})

describe('summary', () => {
  it('给出个数、合计、最大/最小', () => {
    expect(summary([{ name: 'a', weight: 40 }, { name: 'b', weight: 60 }])).toEqual({
      count: 2,
      sum: 100,
      max: 60,
      min: 40,
    })
  })

  it('空列表 max/min 为 0', () => {
    expect(summary([])).toEqual({ count: 0, sum: 0, max: 0, min: 0 })
  })
})
