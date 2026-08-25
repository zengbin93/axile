export type StringTagMode = 'directory' | 'module'

export function splitStringTags(raw: string, mode: StringTagMode): string[] {
  const separator = mode === 'directory' ? /[\n\r]+/ : /[\n\r,，\s]+/
  return normalizeStringList(raw.split(separator))
}

export function normalizeStringList(values: string[]): string[] {
  const seen = new Set<string>()
  return values.flatMap((value) => {
    const normalized = value.trim()
    if (!normalized || seen.has(normalized)) return []
    seen.add(normalized)
    return [normalized]
  })
}

export function appendUniqueStrings(
  current: string[],
  incoming: string[],
): string[] {
  return normalizeStringList([...current, ...incoming])
}
