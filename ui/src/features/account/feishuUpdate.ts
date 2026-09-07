/** 留空保留已保存的 Key，只有明确清除才提交 null。 */
export function feishuKeyPatch(key: string, clear: boolean): { feishu_key?: string | null } {
  if (clear) return { feishu_key: null }
  return key ? { feishu_key: key } : {}
}
