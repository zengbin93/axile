import { expect, test } from 'bun:test'
import { buildSystemNotificationMarkdown } from './systemNotificationMarkdown'
test('系统文档覆盖凭据隔离、两种事件和真实结果边界', () => {
  const markdown = buildSystemNotificationMarkdown()
  expect(markdown).toStartWith('# 系统告警函数')
  for (const field of ['execution_timeout', 'execution_error', 'AXILE_SYSTEM_FEISHU_KEY', 'error.traceback', 'is_test', '15 秒', '不覆盖最近真实告警结果']) expect(markdown).toContain(field)
  expect(markdown).not.toContain('default_feishu_variables')
})
