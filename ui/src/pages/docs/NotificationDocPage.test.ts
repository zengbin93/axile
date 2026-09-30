import { describe, expect, test } from 'bun:test'
import { ASYNC_NOTIFY_CODE, buildNotificationMarkdown, NOTIFY_CODE } from './notificationMarkdown'

describe('notification documentation', () => {
  test('documents the account notification contract and sample code', () => {
    const markdown = buildNotificationMarkdown()
    expect(markdown).toStartWith('# 账户执行通知函数')
    expect(markdown).toContain('notify(context)')
    expect(markdown).toContain('execution.is_test')
    expect(markdown).toContain('试跑可能真的向外发送消息')
    expect(markdown).toContain('最长 15 秒')
    expect(markdown).toContain('不会自动补发默认飞书卡片')
    expect(markdown).toContain(NOTIFY_CODE)
    expect(markdown).toContain(ASYNC_NOTIFY_CODE)
    expect(markdown).toContain("不支持生成器或异步生成器")
    expect(markdown).toContain("未完成任务会被取消")
    expect(markdown).not.toContain('系统执行告警')
  })
})
