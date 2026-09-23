import { expect, test } from 'bun:test'
import { EditorState } from '@codemirror/state'
import { python } from '@codemirror/lang-python'
import { pythonScopes } from './pythonStickyScroll'

function headers(source: string, needle: string) {
  const state = EditorState.create({ doc: source, extensions: [python()] })
  return pythonScopes(state, source.indexOf(needle)).map(scope => state.doc.lineAt(scope.from).text.trim())
}

test('sticky context follows nested Python scopes and preserves multiline declarations', () => {
  expect(headers('class Strategy:\n    async def calculate(\n        self, values\n    ):\n        for value in values:\n            result = value\n', 'result')).toEqual([
    'class Strategy:', 'async def calculate(', 'for value in values:',
  ])
})

test('sticky context switches to the current branch and ignores apparent code in strings', () => {
  expect(headers('def run():\n    if True:\n        pass\n    else:\n        text = "class Fake:"\n', 'text')).toEqual(['def run():', 'else:'])
  expect(headers('text = """\nclass Fake:\n    def fake():\n        content\n"""\n', 'content')).toEqual([])
})

test('top-level statements and single-line suites have no sticky scope', () => {
  expect(headers('def one(): pass\nvalue = 1\n', 'value')).toEqual([])
  expect(headers('def one(): pass\n', 'pass')).toEqual([])
})
