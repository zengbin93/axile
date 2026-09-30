import { extractFeishuKey } from '@/features/account/feishuUpdate'
import type { InitStatusValues } from '@/lib/api/init'

export interface SystemAlertDraft {
  mode: 'default' | 'function'
  code: string
  keyInput: string
  clearKey: boolean
}
export function systemAlertDraft(values: InitStatusValues): SystemAlertDraft {
  return { mode: values.system_execution_notification_mode, code: values.system_execution_notification_code, keyInput: '', clearKey: false }
}
export function systemAlertKey(draft: SystemAlertDraft): string | null {
  return draft.clearKey ? '' : extractFeishuKey(draft.keyInput) || null
}
export function systemAlertEqual(a: SystemAlertDraft, b: SystemAlertDraft): boolean {
  return a.mode === b.mode && a.code === b.code && a.keyInput === b.keyInput && a.clearKey === b.clearKey
}
export function systemAlertLabel(draft: SystemAlertDraft, configured: boolean): string {
  if (draft.mode === 'function') return draft.code.trim() ? '自定义函数' : '自定义函数未配置'
  return (systemAlertKey(draft) ?? (configured ? 'saved' : '')) ? '默认飞书通知' : '未配置'
}
