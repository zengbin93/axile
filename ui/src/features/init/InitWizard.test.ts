import { describe, expect, it } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

describe('InitWizard', () => {
  it('exposes a Tushare Token input in init and advanced edit modes', () => {
    const source = readFileSync(join(import.meta.dir, 'InitWizard.tsx'), 'utf8')

    expect(source).toContain('htmlFor="tushare-token"')
    expect(source.match(/id="tushare-token"/g)).toHaveLength(2)
    expect(source).toContain("<Section label=\"交易日历\">")
  })
})
