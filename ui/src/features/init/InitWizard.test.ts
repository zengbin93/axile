import { describe, expect, it } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

describe('InitWizard', () => {
  it('does not expose a Tushare Token input', () => {
    const source = readFileSync(join(import.meta.dir, 'InitWizard.tsx'), 'utf8')

    expect(source).not.toContain('tushare')
  })
})
