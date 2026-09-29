import { describe, expect, it } from 'bun:test'
import { fixAtPosition, type HoverFix } from './pythonHoverFix'

describe('Python hover quick fix', () => {
  it('finds the fix at the hovered symbol, preferring the narrower diagnostic', () => {
    const fixes: HoverFix[] = [
      { from: 4, to: 25, message: 'line issue', source: 'ty', canFix: false },
      { from: 10, to: 17, message: 'context issue', source: '入口契约', canFix: true },
    ]
    expect(fixAtPosition(fixes, 12)?.message).toBe('context issue')
    expect(fixAtPosition(fixes, 6)?.message).toBe('line issue')
    expect(fixAtPosition(fixes, 30)).toBeNull()
  })
})
