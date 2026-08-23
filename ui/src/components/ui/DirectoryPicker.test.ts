import { describe, expect, it } from 'bun:test'

import { directoryBreadcrumbs } from './directoryPath'

describe('directoryBreadcrumbs', () => {
  it('构造 Windows 路径面包屑', () => {
    expect(directoryBreadcrumbs('C:\\Program Files\\GoldMiner3')).toEqual([
      { label: 'C:', path: 'C:\\' },
      { label: 'Program Files', path: 'C:\\Program Files\\' },
      { label: 'GoldMiner3', path: 'C:\\Program Files\\GoldMiner3\\' },
    ])
  })

  it('构造 POSIX 路径面包屑', () => {
    expect(directoryBreadcrumbs('/opt/goldminer3')).toEqual([
      { label: '/', path: '/' },
      { label: 'opt', path: '/opt' },
      { label: 'goldminer3', path: '/opt/goldminer3' },
    ])
  })
})
