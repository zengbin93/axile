import { expect, test } from 'bun:test'
import { notificationDraft } from './notificationDraft'

test('未配置账户打开编辑器时显示默认函数草稿，已有自定义函数保持原样', () => {
  expect(notificationDraft(null, 'default')).toEqual({ code: 'default', savedCode: '' })
  expect(notificationDraft('custom', 'default')).toEqual({ code: 'custom', savedCode: 'custom' })
})
