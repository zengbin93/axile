import { describe, expect, it } from 'bun:test'

import {
  INK_REWRITE_MS_LABEL,
  INK_REWRITE_MS_PROSE,
  inkRewriteMs,
  nextInkPair,
  type InkPair,
} from './InkRewrite'

describe('nextInkPair', () => {
  const base: InkPair = { cur: '▶ 启动', curCls: 'text-ink-1', prev: null, prevCls: null, gen: 0 }

  it('首帧只就位、不产生退场层', () => {
    expect(nextInkPair(base, '▶ 启动', 'text-ink-1', true)).toEqual({
      cur: '▶ 启动',
      curCls: 'text-ink-1',
      prev: null,
      prevCls: null,
      gen: 0,
    })
    expect(nextInkPair(base, '⏸ 暂停', 'text-ink-1', true)).toEqual({
      cur: '⏸ 暂停',
      curCls: 'text-ink-1',
      prev: null,
      prevCls: null,
      gen: 0,
    })
  })

  it('文案与墨均未变时保持原对', () => {
    const next = nextInkPair(base, '▶ 启动', 'text-ink-1', false)
    expect(next).toBe(base)
  })

  it('文案未变而墨变时就地换墨、不触发重写', () => {
    const next = nextInkPair(base, '▶ 启动', 'text-warn', false)
    expect(next).toEqual({ ...base, curCls: 'text-warn' })
    expect(next.prev).toBeNull()
    expect(next.gen).toBe(0)
  })

  it('文案变化时旧句连同旧墨进 prev、gen 递增（日记重写）', () => {
    const next = nextInkPair(base, '⏸ 暂停', 'text-accent', false)
    expect(next).toEqual({
      cur: '⏸ 暂停',
      curCls: 'text-accent',
      prev: '▶ 启动',
      prevCls: 'text-ink-1',
      gen: 1,
    })
  })

  it('连续重写始终以当前 cur/curCls 为退场源', () => {
    const mid = nextInkPair(base, '⏸ 暂停', 'text-accent', false)
    const again = nextInkPair(mid, '自动执行已暂停 · 仅手动触发', 'text-ink-2', false)
    expect(again.prev).toBe('⏸ 暂停')
    expect(again.prevCls).toBe('text-accent')
    expect(again.cur).toBe('自动执行已暂停 · 仅手动触发')
    expect(again.curCls).toBe('text-ink-2')
    expect(again.gen).toBe(2)
  })
})

describe('inkRewriteMs', () => {
  it('慢于工具台默认档，贴近电影墨褪节奏', () => {
    expect(INK_REWRITE_MS_LABEL).toBe(420)
    expect(INK_REWRITE_MS_PROSE).toBe(620)
    expect(inkRewriteMs('label')).toBe(INK_REWRITE_MS_LABEL)
    expect(inkRewriteMs('prose')).toBe(INK_REWRITE_MS_PROSE)
    // prose 更「写完一行」
    expect(INK_REWRITE_MS_PROSE).toBeGreaterThan(INK_REWRITE_MS_LABEL)
    // 明显慢于 200ms 标准路由档
    expect(INK_REWRITE_MS_LABEL).toBeGreaterThan(200)
  })
})
