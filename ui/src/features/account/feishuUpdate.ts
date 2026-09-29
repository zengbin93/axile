/** 留空保留已保存的 Key，只有明确清除才提交 null。 */
export function feishuKeyPatch(key: string, clear: boolean): { feishu_key?: string | null } {
  if (clear) return { feishu_key: null }
  return key ? { feishu_key: key } : {}
}

/** 接受裸 Key 或完整机器人 Webhook 链接。 */
export function extractFeishuKey(raw: string): string {
  const value = raw.trim()
  const match = value.match(/hook\/([^/?#\s]+)/i)
  return match ? match[1] : value
}
