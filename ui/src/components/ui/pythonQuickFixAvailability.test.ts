import { describe, expect, it } from 'bun:test'
import type { CodeAction, Command, Diagnostic } from 'vscode-languageserver-protocol'
import { actionTargetsDiagnostic } from './pythonQuickFixAvailability'

const range = { start: { line: 3, character: 11 }, end: { line: 3, character: 16 } }
const diagnostic = { range, code: 'invalid-key', message: 'Unknown key', severity: 1, source: 'ty' } as Diagnostic

describe('diagnostic hover quick fix availability', () => {
  it('shows the button only for actions attached to that diagnostic', () => {
    const action: CodeAction = { title: 'Replace with "name"', kind: 'quickfix', diagnostics: [diagnostic] }
    expect(actionTargetsDiagnostic(action, diagnostic)).toBe(true)
    expect(actionTargetsDiagnostic(action, { ...diagnostic, code: 'missing-typed-dict-key' })).toBe(false)
    expect(actionTargetsDiagnostic({ title: 'Unavailable', disabled: { reason: 'Unavailable' }, diagnostics: [diagnostic] }, diagnostic)).toBe(false)
    const command: Command = { title: 'Other command', command: 'other.command' }
    expect(actionTargetsDiagnostic(command, diagnostic)).toBe(false)
  })
})
