import { describe, expect, test } from 'bun:test'
import { basicNotificationPatch, basicNotificationStatus } from '@/features/account/basicNotification'

const template = 'def notify(context): pass'
const custom = 'def notify(context): print(context)'

describe('基本信息通知提交契约', () => {
  test.each([
    [null, null, 'https://open.feishu.cn/open-apis/bot/v2/hook/new-key', false, { feishu_key: 'new-key', execution_notification_code: template }],
    [null, null, 'new-key', false, { feishu_key: 'new-key', execution_notification_code: template }],
    [template, template, 'new-key', false, { feishu_key: 'new-key' }],
    [template, template, '', true, { feishu_key: null, execution_notification_code: null }],
    [custom, template, '', false, { execution_notification_code: template }],
    [custom, template, '', true, { feishu_key: null, execution_notification_code: null }],
    [null, null, '', false, {}],
    [custom, custom, '', false, {}],
    [template, template, '', false, {}],
  ] as const)('源码 %s、草稿 %s、输入 %s、清除 %s', (saved, code, input, clear, expected) => {
    expect(basicNotificationPatch(saved, code, input, clear, template)).toEqual(expected)
  })

  test('模板未读取时保留 Key 修改，保存前再获取模板', () => {
    expect(basicNotificationPatch(null, null, 'new-key', false, null)).toEqual({ feishu_key: 'new-key' })
  })
  test('清除和撤销清除保留重置前后的源码草稿', () => {
    const saved = { execution_notification_code: custom, execution_notification_status: 'function' as const }
    expect(basicNotificationStatus(saved, custom, false, null)).toBe('function')
    expect(basicNotificationStatus(saved, template, false, template)).toBe('default')
    expect(basicNotificationStatus(saved, template, true, template)).toBe('none')
    expect(basicNotificationStatus(saved, template, false, template)).toBe('default')
    expect(basicNotificationPatch(custom, template, '', false, template)).toEqual({ execution_notification_code: template })
  })
  test('状态忽略首尾空白，Webhook 不参与分类', () => {
    const saved = { execution_notification_code: custom, execution_notification_status: 'function' as const }
    expect(basicNotificationStatus(saved, `\n${template}\n`, false, template)).toBe('default')
    expect(basicNotificationStatus(saved, '  ', false, template)).toBe('none')
  })
})
