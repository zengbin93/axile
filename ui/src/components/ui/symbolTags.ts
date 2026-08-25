/** 按页面既有口径拆分品种代码，同时保留用户输入的大小写。 */
export function splitSymbols(raw: string): string[] {
  return raw
    .split(/[\n,，\s]+/)
    .map((symbol) => symbol.trim())
    .filter(Boolean)
}

/** 在保序的前提下追加品种并去重。 */
export function appendUniqueSymbols(current: string[], incoming: string[]): string[] {
  const seen = new Set(current)
  return [
    ...current,
    ...incoming.filter((symbol) => {
      if (seen.has(symbol)) return false
      seen.add(symbol)
      return true
    }),
  ]
}
