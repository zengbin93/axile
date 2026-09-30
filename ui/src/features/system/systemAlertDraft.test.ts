import { expect, test } from 'bun:test'
import { systemAlertKey, systemAlertLabel } from './systemAlertDraft'
const draft = { mode: 'default' as const, code: 'def notify(context): pass', keyInput: '', clearKey: false }
test('空输入保留已有 Key，显式清除才提交空串', () => {
  expect(systemAlertKey(draft)).toBeNull()
  expect(systemAlertKey({ ...draft, clearKey: true })).toBe('')
  expect(systemAlertKey({ ...draft, keyInput: 'https://open.feishu.cn/open-apis/bot/v2/hook/new-key' })).toBe('new-key')
  expect(systemAlertLabel(draft, true)).toBe('默认飞书通知')
  expect(systemAlertLabel({ ...draft, clearKey: true }, true)).toBe('未配置')
})
test('模式决定当前状态，备用源码不启用自定义', () => {
  expect(systemAlertLabel(draft, false)).toBe('未配置')
  expect(systemAlertLabel({ ...draft, mode: 'function' }, false)).toBe('自定义函数')
})
