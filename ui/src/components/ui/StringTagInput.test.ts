import { describe, expect, test } from 'bun:test'

import {
  appendUniqueStrings,
  normalizeStringList,
  splitStringTags,
} from '@/components/ui/stringList'

describe('StringTagInput helpers', () => {
  test('目录模式保留路径空格，只按换行拆分', () => {
    expect(
      splitStringTags('/srv/my algorithms\n ./local algorithms ', 'directory'),
    ).toEqual(['/srv/my algorithms', './local algorithms'])
  })

  test('模块模式支持空格、逗号和换行批量输入', () => {
    expect(splitStringTags('pkg.a, pkg.b\n包.模块', 'module')).toEqual([
      'pkg.a',
      'pkg.b',
      '包.模块',
    ])
  })

  test('整理空值、首尾空格和重复项并保持顺序', () => {
    expect(normalizeStringList([' pkg.a ', '', 'pkg.b', 'pkg.a'])).toEqual([
      'pkg.a',
      'pkg.b',
    ])
  })

  test('追加新值时保序去重', () => {
    expect(appendUniqueStrings(['pkg.a'], [' pkg.b ', 'pkg.a', ''])).toEqual([
      'pkg.a',
      'pkg.b',
    ])
  })
})
