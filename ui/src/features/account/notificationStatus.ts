import type { Account } from '@/types/api'

export const NOTIFICATION_STATUS_LABEL: Record<Account['execution_notification_status'], string> = {
  none: '未设置通知',
  default: '默认通知',
  function: '自定义函数',
}
