import { describe, expect, it } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

describe('InitWizard', () => {
  it('associates the Tushare Token label with its password input', () => {
    const source = readFileSync(join(import.meta.dir, 'InitWizard.tsx'), 'utf8')

    expect(source).toContain('htmlFor="tushare-token"')
    expect(source).toContain('id="tushare-token"')
  })
})
