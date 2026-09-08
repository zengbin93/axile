import { expect, test } from 'bun:test'
import { isCurrentTabClick, navigationPath } from '@/lib/navigationPreparation'

const click = { defaultPrevented: false, button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }
test('先尊重调用方取消事件，并保留修饰键和新标签页语义', () => {
  expect(isCurrentTabClick(click)).toBe(true)
  expect(isCurrentTabClick(click, '_self')).toBe(true)
  for (const key of ['defaultPrevented', 'metaKey', 'ctrlKey', 'shiftKey', 'altKey']) expect(isCurrentTabClick({ ...click, [key]: true })).toBe(false)
  expect(isCurrentTabClick({ ...click, button: 1 })).toBe(false)
  expect(isCurrentTabClick(click, '_blank')).toBe(false)
  expect(isCurrentTabClick(click, 'other')).toBe(false)
  expect(isCurrentTabClick(click, undefined, true)).toBe(false)
  expect(isCurrentTabClick(click, undefined, false, '')).toBe(false)
})
test('相对路由、相对路径、查询和对象导航保持各自解析语义', () => {
  const paths = ['/', '/accounts/2', '/accounts/2/history']
  for (const to of ['..', '..?from=history', { pathname: '..', search: '?from=history' }]) {
    expect(navigationPath(to, '/accounts/2/history', paths)).toBe('/accounts/2')
  }
  expect(navigationPath('../..', '/accounts/2/history', paths)).toBe('/')
  expect(navigationPath('../..', '/accounts/2/history', paths, 'path')).toBe('/accounts')
  expect(navigationPath('?x=1', '/accounts/2/history', paths)).toBe('/accounts/2/history')
  expect(navigationPath('/accounts/3', '/accounts/2/history', paths)).toBe('/accounts/3')
})
