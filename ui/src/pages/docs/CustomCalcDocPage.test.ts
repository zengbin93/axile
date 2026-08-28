import { describe, expect, test } from 'bun:test'
import { buildCustomCalcMarkdown, CUSTOM_CALC_NOTES } from './customCalcMarkdown'

describe('customCalcMarkdown', () => {
  test('serializes the complete document as Markdown', () => {
    const markdown = buildCustomCalcMarkdown(
      [{ name: 'account', type: 'UnifiedAccountAssets', desc: '账户资产快照' }],
      'def calculate_portfolio(context):\n    return {}',
      [{ key: 'tq', title: '读取 TQ 合约乘数', desc: '渠道示例。', code: 'multiplier = 10' }],
      ['优先使用 `context` 的通用接口'],
    )

    expect(markdown).toStartWith('# 开发自定义组合逻辑')
    expect(markdown).toContain('| `account` | `UnifiedAccountAssets` |')
    expect(markdown).toContain('```python\ndef calculate_portfolio(context):')
    expect(markdown).toContain('### 读取 TQ 合约乘数')
    expect(markdown).toContain('- 优先使用 `context` 的通用接口')
  })

  test('documents the shared live executor and worker recovery boundary', () => {
    const markdown = buildCustomCalcMarkdown([], '', [], CUSTOM_CALC_NOTES)

    expect(markdown).toContain('完整、共享且常驻的真实渠道执行器')
    expect(markdown).toContain('直接调用交易方法会立即产生渠道副作用')
    expect(markdown).toContain('系统会在下次调用时重建 worker')
    expect(markdown).toContain('样例试跑使用一次性进程')
  })
})
