import { EditorView } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags } from '@lezer/highlight'

/** 草稿与只读源码共享全局主题 token，亮暗主题无需重建编辑器。 */
export const pythonEditorTheme = [
  EditorView.theme({
    '&': { backgroundColor: 'var(--color-code-bg)', color: 'var(--color-code-fg)', fontSize: '14px' },
    '&.cm-focused': { outline: 'none' },
    '.cm-gutters': { backgroundColor: 'var(--color-code-bg)', color: 'var(--color-ink-3)', border: 'none' },
    '.cm-content': { fontFamily: 'var(--font-mono)' },
    '.cm-cursor': { borderLeftColor: 'var(--color-code-fg)' },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {
      backgroundColor: 'var(--color-code-selection) !important',
    },
  }),
  syntaxHighlighting(HighlightStyle.define([
    { tag: [tags.keyword, tags.modifier, tags.controlKeyword, tags.operatorKeyword], color: 'var(--color-code-keyword)' },
    { tag: [tags.variableName, tags.propertyName], color: 'var(--color-code-name)' },
    { tag: [tags.function(tags.variableName), tags.definition(tags.variableName)], color: 'var(--color-code-function)' },
    { tag: [tags.string, tags.special(tags.string)], color: 'var(--color-code-string)' },
    { tag: [tags.number, tags.bool, tags.null], color: 'var(--color-code-number)' },
    { tag: [tags.className, tags.typeName, tags.namespace], color: 'var(--color-code-type)' },
    { tag: [tags.comment, tags.lineComment, tags.blockComment], color: 'var(--color-code-comment)', fontStyle: 'italic' },
    { tag: [tags.operator, tags.punctuation], color: 'var(--color-code-fg)' },
  ])),
]
