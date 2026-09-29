import type { CodeAction, Command, Diagnostic } from 'vscode-languageserver-protocol'

/** ty 把可修复诊断附在 Code Action 上；只为对应的 hover 提供按钮。 */
export function actionTargetsDiagnostic(action: CodeAction | Command, diagnostic: Pick<Diagnostic, 'code' | 'range'>): boolean {
  if (typeof action.command === 'string' || !('diagnostics' in action) || ('disabled' in action && action.disabled)) return false
  return (action.diagnostics ?? []).some((target) =>
    target.code === diagnostic.code
    && target.range.start.line === diagnostic.range.start.line
    && target.range.start.character === diagnostic.range.start.character
    && target.range.end.line === diagnostic.range.end.line
    && target.range.end.character === diagnostic.range.end.character,
  )
}
