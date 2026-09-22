import { expect, test } from 'bun:test'
import { Text } from '@codemirror/state'
import { semanticDecorations, workspaceEdits } from './pythonLanguageFeatures'

test('workspace edits reject cross-file changes before any draft edit is applied', () => {
  const edit = { range: { start: { line: 0, character: 0 }, end: { line: 0, character: 1 } }, newText: 'name' }
  expect(workspaceEdits({ changes: { 'file:///draft.py': [edit] } }, 'file:///draft.py')).toEqual([edit])
  expect(() => workspaceEdits({ changes: { 'file:///draft.py': [edit], 'file:///dependency.py': [edit] } }, 'file:///draft.py')).toThrow('依赖源码')
  expect(() => workspaceEdits({ documentChanges: [{ kind: 'create', uri: 'file:///new.py' }] }, 'file:///draft.py')).toThrow('跨文件')
})

test('semantic token deltas preserve UTF-16 positions after Chinese and emoji', () => {
  const doc = Text.of(['中文😀 value', '    call()'])
  const marks = semanticDecorations(doc, [0, 5, 5, 0, 0, 1, 4, 4, 1, 0], ['variable', 'function'])
  expect(marks.map((mark) => doc.sliceString(mark.from, mark.to))).toEqual(['value', 'call'])
})

test('malformed semantic ranges do not create decorations outside the document', () => {
  expect(semanticDecorations(Text.of(['x']), [0, 0, 50, 0, 0, 5, 0, 1, 0, 0], ['variable'])).toEqual([])
})
