import { expect, test } from 'bun:test'
import { extractFeishuKey, feishuKeyPatch } from './feishuUpdate'

test('通知 Key 支持保留、替换、清除和撤销清除', () => {
  expect(feishuKeyPatch('', false)).toEqual({})
  expect(feishuKeyPatch('new-key', false)).toEqual({ feishu_key: 'new-key' })
  expect(feishuKeyPatch('', true)).toEqual({ feishu_key: null })
  expect(feishuKeyPatch('', false)).toEqual({})
})

test('接受完整 Webhook 链接和裸 Key', () => {
  expect(extractFeishuKey('https://open.feishu.cn/open-apis/bot/v2/hook/abc?x=1')).toBe('abc')
  expect(extractFeishuKey(' abc ')).toBe('abc')
})
