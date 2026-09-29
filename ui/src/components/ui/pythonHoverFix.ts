import type { EditorView } from '@codemirror/view'
import type { Action } from '@codemirror/lint'

export interface HoverFix {
  from: number
  to: number
  message: string
  action: Action
}

/** 选择鼠标所在诊断；多个范围重叠时优先取最具体的一条。 */
export function fixAtPosition(fixes: HoverFix[], position: number): HoverFix | null {
  return fixes
    .filter((fix) => fix.from <= position && position <= fix.to)
    .sort((left, right) => (left.to - left.from) - (right.to - right.from))[0] ?? null
}

export function applyHoverFix(view: EditorView, fix: HoverFix): void {
  fix.action.apply(view, fix.from, fix.to)
}
