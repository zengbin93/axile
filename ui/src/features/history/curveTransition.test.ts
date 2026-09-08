import { expect, test } from 'bun:test'
import { curveReturnDestination } from '@/features/history/curveTransition'

test('返回身份由本次目的地决定，不需要来源历史记录', () => {
  expect(curveReturnDestination('/accounts/2/history', '/accounts/2')).toEqual({ accountId: 2, identity: 'performance-source-detail-2' })
  expect(curveReturnDestination('/accounts/2/history', '/')).toEqual({ accountId: 2, identity: 'performance-source-fleet-2' })
  expect(curveReturnDestination('/accounts/12/history/', '/accounts/12/')).toEqual({ accountId: 12, identity: 'performance-source-detail-12' })
})

test('其他账户、其他页面与非绩效来源不准备收回', () => {
  for (const target of ['/accounts/3', '/accounts/2/positions', '/accounts/2/executions', '/accounts/2/settings', '/accounts/2/history']) {
    expect(curveReturnDestination('/accounts/2/history', target)).toBeNull()
  }
  expect(curveReturnDestination('/accounts/2', '/')).toBeNull()
})

test('正向导航以目的绩效账户和当前概览选择小曲线，隔离其他子页与账户', () => {
  // 正向复用同一账户身份解析，交换大图与小图页面的位置。
  const source = (from: string, to: string) => curveReturnDestination(to, from)
  expect(source('/accounts/2', '/accounts/2/history')?.identity).toBe('performance-source-detail-2')
  expect(source('/', '/accounts/2/history')?.identity).toBe('performance-source-fleet-2')
  for (const from of ['/accounts/3', '/accounts/2/holdings', '/accounts/2/history']) {
    expect(source(from, '/accounts/2/history')).toBeNull()
  }
})
