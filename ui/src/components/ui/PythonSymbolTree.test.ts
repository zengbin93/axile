import { describe, expect, it } from 'bun:test'
import { SymbolKind, type DocumentSymbol, type SymbolInformation } from 'vscode-languageserver-protocol'

import { symbolKey, symbolPath } from './PythonSymbolTree'

const range = (start: number, end: number) => ({ start: { line: start, character: 0 }, end: { line: end, character: 0 } })
const method = (name: string, line: number): DocumentSymbol => ({ name, kind: SymbolKind.Method, range: range(line, line + 4), selectionRange: range(line, line) })

describe('PythonSymbolTree paths', () => {
  it('展开光标所在符号的祖先路径', () => {
    const symbols: DocumentSymbol[] = [{ name: 'Client', kind: SymbolKind.Class, range: range(0, 30), selectionRange: range(0, 0), children: [method('fetch', 4), method('save', 12)] }]
    expect(symbolPath(symbols, 5, 2)).toEqual([symbolKey(symbols[0]), symbolKey(symbols[0].children![0])])
    expect(symbolPath(symbols, 35, 0)).toEqual([])
  })

  it('同名符号使用位置区分，平铺结果不伪造层级', () => {
    expect(symbolKey(method('run', 1))).not.toBe(symbolKey(method('run', 10)))
    const flat: SymbolInformation[] = [{ name: 'run', kind: SymbolKind.Function, location: { uri: 'file:///test.py', range: range(1, 2) } }]
    expect(symbolPath(flat, 1, 0)).toEqual([])
  })
})
