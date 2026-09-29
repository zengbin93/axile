/** 未配置的账户打开编辑器时展示默认源码，保留空的已保存值。 */
export function notificationDraft(savedCode: string | null, defaultCode: string): { code: string; savedCode: string } {
  const saved = savedCode ?? ''
  return { code: saved || defaultCode, savedCode: saved }
}
