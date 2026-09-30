import type { Account } from '@/types/api'
import { extractFeishuKey, feishuKeyPatch } from '@/features/account/feishuUpdate'
import type { AccountUpdatePayload } from '@/lib/api/accounts'

/** 清除只覆盖预览及提交值，原通知草稿留存供撤销恢复。 */
export function basicNotificationStatus(saved: Pick<Account, 'execution_notification_status' | 'execution_notification_code'>, code: string | null, clear: boolean, defaultCode: string | null): Account['execution_notification_status'] {
  if (clear || !code?.trim()) return 'none'
  if (defaultCode !== null && code.trim() === defaultCode.trim()) return 'default'
  if (code.trim() === saved.execution_notification_code?.trim()) return saved.execution_notification_status
  return 'function'
}

/** 启用默认通知必须显式提交模板；模板尚未读取时由保存流程先获取。 */
export function basicNotificationPatch(savedCode: string | null, code: string | null, input: string, clear: boolean, defaultCode: string | null): AccountUpdatePayload {
  if (clear) return { feishu_key: null, execution_notification_code: null }
  const key = extractFeishuKey(input)
  const patch: AccountUpdatePayload = feishuKeyPatch(key, false)
  if ((code ?? '').trim() !== (savedCode ?? '').trim()) patch.execution_notification_code = code
  if (key && !code?.trim() && defaultCode !== null) patch.execution_notification_code = defaultCode
  return patch
}
