import type { TextEdit } from 'vscode-languageserver-protocol'
import { apiSend } from '@/lib/api/client'

export type PythonEditorKind = 'portfolio' | 'account_notification' | 'system_notification'

export interface ContractDiagnostic {
  code?: string
  range: TextEdit['range']
  severity: number
  message: string
  source: string
}

export interface ContractFix {
  title: string
  edits: TextEdit[]
}

export interface ContractReport {
  diagnostics: ContractDiagnostic[]
  fixes: ContractFix[]
}

export function checkPythonContract(code: string, kind: PythonEditorKind): Promise<ContractReport> {
  return apiSend<ContractReport>('POST', '/editor/contract', { code, kind })
}
