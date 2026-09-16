/** 与统一资产模型同约定：只排除明确降级来源，自定义来源保留事实。 */
export function isDegradedSnapshotSource(source: unknown): boolean {
  return source === 'assumed' || source === 'error' || source === 'unavailable'
}
