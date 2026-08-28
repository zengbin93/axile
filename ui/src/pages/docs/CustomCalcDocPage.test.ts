import { describe, expect, test } from 'bun:test'
import { buildCustomCalcMarkdown } from './customCalcMarkdown'

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
})
