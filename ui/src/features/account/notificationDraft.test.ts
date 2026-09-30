import { expect, test } from 'bun:test'
import { notificationDraft } from './notificationDraft'

test('未配置账户打开编辑器时显示默认函数草稿，已有自定义函数保持原样', () => {
  expect(notificationDraft(null, 'default')).toEqual({ code: 'default', savedCode: '' })
  expect(notificationDraft('custom', 'default')).toEqual({ code: 'custom', savedCode: 'custom' })
})

test('仅含空白的已保存源码仍展示未保存的默认草稿', () => {
  expect(notificationDraft(' \n ', 'default')).toEqual({ code: 'default', savedCode: ' \n ' })
})
