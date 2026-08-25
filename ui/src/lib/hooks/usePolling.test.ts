import { describe, expect, it } from 'bun:test'

import { pollingView } from '@/lib/hooks/usePolling'

describe('pollingView', () => {
  const ready = {
    key: 'account:1',
    data: { value: 1 },
    error: null,
    loading: false,
    refreshing: false,
    updatedAt: 123,
  }

  it('新 queryKey 首帧隐藏旧实体并进入冷加载', () => {
    expect(pollingView(ready, 'account:2', true)).toEqual({
      data: null,
      error: null,
      loading: true,
      refreshing: false,
      updatedAt: null,
    })
  })

  it('同 queryKey 后台刷新保留旧数据', () => {
    expect(pollingView({ ...ready, refreshing: true }, 'account:1', true)).toEqual({
      data: { value: 1 },
      error: null,
      loading: false,
      refreshing: true,
      updatedAt: 123,
    })
  })

  it('disabled 查询不暴露缓存，也不声称正在加载', () => {
    expect(pollingView(ready, 'account:1', false)).toEqual({
      data: null,
      error: null,
      loading: false,
      refreshing: false,
      updatedAt: null,
    })
  })
})
