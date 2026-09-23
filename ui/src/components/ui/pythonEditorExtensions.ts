import { EditorState, Prec } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { indentUnit } from '@codemirror/language'
import { indentWithTab, toggleComment } from '@codemirror/commands'
import { openSearchPanel, gotoLine, search, selectNextOccurrence } from '@codemirror/search'
import { acceptCompletion, completionStatus } from '@codemirror/autocomplete'
import { indentationMarkers } from '@replit/codemirror-indentation-markers'

export const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

export function editingExtensions(format: () => void, run: () => void) {
  return [
    indentUnit.of('    '),
    EditorState.tabSize.of(4),
    search({ top: true }),
    indentationMarkers({ colors: {
      light: 'var(--color-line)', dark: 'var(--color-line)',
      activeLight: 'var(--color-ink-3)', activeDark: 'var(--color-ink-3)',
    } }),
    Prec.high(keymap.of([
      { key: 'Mod-Enter', run: () => { run(); return true } },
      { key: 'Shift-Alt-f', run: () => { format(); return true } },
      { key: 'Mod-/', run: toggleComment },
      { key: 'Mod-d', run: selectNextOccurrence },
      { key: 'Mod-g', run: gotoLine },
      { key: 'Mod-h', mac: 'Mod-Alt-f', run: openSearchPanel },
      { key: 'Tab', run: (view) => completionStatus(view.state) === 'active' && acceptCompletion(view) },
      indentWithTab,
    ])),
    EditorState.phrases.of({
      'Find': '查找', 'Replace': '替换', 'next': '下一个', 'previous': '上一个',
      'all': '全部', 'match case': '区分大小写', 'by word': '全词匹配',
      'regexp': '正则表达式', 'replace': '替换', 'replace all': '全部替换',
      'close': '关闭', 'Go to line': '跳转到行', 'go': '跳转',
      'No diagnostics': '暂无代码问题',
    }),
    EditorView.theme({
      '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'color-mix(in srgb, var(--color-code-selection) 22%, transparent)' },
      '.cm-panels, .cm-tooltip': { backgroundColor: 'var(--color-surface)', color: 'var(--color-ink-1)', borderColor: 'var(--color-line)' },
      '.cm-search input, .cm-textfield': { backgroundColor: 'var(--color-code-bg)', color: 'var(--color-code-fg)' },
      '.cm-button': { backgroundImage: 'none', backgroundColor: 'var(--color-surface)', color: 'var(--color-ink-1)' },
      '.cm-diagnostic-error, .cm-diagnostic-warning': { borderLeftColor: 'var(--color-warn)' },
      '.cm-lintRange-error, .cm-lintRange-warning': { backgroundImage: 'none', textDecoration: 'underline wavy var(--color-warn)', textUnderlineOffset: '3px' },
      '.cm-lint-marker-error, .cm-lint-marker-warning': { content: '"△"', color: 'var(--color-warn)' },
      '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'var(--color-code-selection)', color: 'var(--color-code-fg)' },
      '.cm-matchingBracket': { backgroundColor: 'var(--color-code-selection)', outline: '1px solid var(--color-ink-3)' },
    }),
  ]
}
