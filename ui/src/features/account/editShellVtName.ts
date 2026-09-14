/** 入口卡 ↔ 子页顶栏 共享容器名（同构壳 FLIP，非文案内容 morph）。 */
export function editShellVtName(accountId: number, kind: 'timer' | 'algorithm' | 'control'): string {
  return `edit-shell-${kind}-${accountId}`
}

