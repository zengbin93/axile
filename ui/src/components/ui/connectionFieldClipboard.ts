import {
  connectionValueError,
  isWindowsAbsoluteDirectory,
  normalizeMoneyValue,
  type ConnectionFieldKind,
} from '@/components/ui/connectionFieldValue'
import type { ChannelAccountFieldClipboard, ChannelAccountFieldConstraints } from '@/types/api'

export type ClipboardCandidateRole = ChannelAccountFieldClipboard['role']

export interface ClipboardCandidate {
  id: string
  kind: ConnectionFieldKind
  value: string
  displayValue: string
  sourceLabel?: string
  role?: ClipboardCandidateRole
  derived?: boolean
}

export interface ClipboardParseContext {
  kind: ConnectionFieldKind
  fieldLabel: string
  placeholder?: string
  clipboard?: ChannelAccountFieldClipboard | null
  constraints?: ChannelAccountFieldConstraints | null
}

export interface ClipboardParseResult {
  candidates: ClipboardCandidate[]
  warning?: string
}

export type ClipboardPasteResolution =
  | { action: 'error'; warning: string }
  | { action: 'commit'; candidate: ClipboardCandidate; warning?: string }
  | { action: 'choose'; candidates: ClipboardCandidate[]; warning?: string }

const MAX_CANDIDATES = 20
const ENDPOINT_PATTERN = /(?:tcp|https?|wss?|ftp):\/\/(?:\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::\d{1,5})?(?:\/[^\s"'<>]*)?|(?:\[[0-9a-f:]+\]|(?:[a-z0-9-]+\.)*[a-z0-9-]+):\d{1,5}/gi

/** 剪贴板异常属于浏览器实现细节，不向用户透传原始英文或权限对象。 */
export function clipboardReadFailureMessage(): string {
  return '无法读取剪贴板，请使用 Ctrl/Cmd+V 或系统粘贴'
}

function candidateId(kind: ConnectionFieldKind, value: string, role?: ClipboardCandidateRole): string {
  let hash = 5381
  const source = `${kind}\0${role ?? ''}\0${value}`
  for (let index = 0; index < source.length; index += 1) hash = ((hash << 5) + hash) ^ source.charCodeAt(index)
  return `${kind}-${(hash >>> 0).toString(36)}`
}

function stripPairedQuotes(value: string): string {
  const trimmed = value.trim()
  if (trimmed.length < 2) return trimmed
  const first = trimmed[0]
  const last = trimmed[trimmed.length - 1]
  return (first === '"' && last === '"') || (first === "'" && last === "'")
    ? trimmed.slice(1, -1).trim()
    : trimmed
}

function roleFromPrefix(prefix: string): ClipboardCandidateRole | undefined {
  const value = prefix.toLowerCase()
  const patterns: Array<[ClipboardCandidateRole, RegExp]> = [
    ['trading', /交易前置|\btd_front\b|\btrader\b|trade[ _-]*front/gi],
    ['market-data', /行情前置|\bmd_front\b|\bmarket\b|quote[ _-]*front/gi],
    ['rpc', /\brpc\b|\bserv_addr\b|\bhostaddr\b|\brpcport\b/gi],
    ['proxy', /代理|\bproxy\b/gi],
  ]
  let nearest: { index: number; role: ClipboardCandidateRole } | undefined
  for (const [role, pattern] of patterns) {
    for (const match of value.matchAll(pattern)) {
      const index = match.index ?? -1
      if (!nearest || index > nearest.index) nearest = { index, role }
    }
  }
  return nearest?.role
}

function roleLabel(role?: ClipboardCandidateRole): string | undefined {
  if (role === 'trading') return '交易前置'
  if (role === 'market-data') return '行情前置'
  if (role === 'rpc') return 'RPC 地址'
  if (role === 'proxy') return '代理地址'
  return undefined
}

function cleanEndpoint(value: string): string {
  return value.replace(/[),;]+$/g, '')
}

function endpointCandidates(raw: string, context: ClipboardParseContext): ClipboardCandidate[] {
  const found: Array<{ value: string; prefix: string }> = []
  for (const line of raw.split(/\r?\n/)) {
    ENDPOINT_PATTERN.lastIndex = 0
    for (const match of line.matchAll(ENDPOINT_PATTERN)) {
      const value = cleanEndpoint(match[0])
      const index = match.index ?? 0
      found.push({ value, prefix: line.slice(0, index) })
    }
  }

  const byValue = new Map<string, ClipboardCandidate>()
  for (const item of found) {
    if (connectionValueError({
      kind: 'endpoint',
      value: item.value,
      required: true,
      label: context.fieldLabel,
      placeholder: context.placeholder,
      constraints: context.constraints,
    })) continue
    const role = roleFromPrefix(item.prefix)
    const existing = byValue.get(item.value)
    if (existing) {
      if (!existing.role && role) {
        existing.role = role
        existing.sourceLabel = roleLabel(role)
        existing.id = candidateId('endpoint', existing.value, role)
      }
      continue
    }
    byValue.set(item.value, {
      id: candidateId('endpoint', item.value, role),
      kind: 'endpoint',
      value: item.value,
      displayValue: item.value,
      role,
      sourceLabel: roleLabel(role),
    })
  }
  return [...byValue.values()]
}

function windowsPathFromLine(line: string): string | null {
  const quoted = line.match(/["']([a-z]:[\\/][^"']+|\\\\[^"']+)["']/i)
  if (quoted) return quoted[1].trim()
  const driveIndex = line.search(/[a-z]:[\\/]/i)
  const uncIndex = line.indexOf('\\\\')
  const index = driveIndex >= 0 && uncIndex >= 0 ? Math.min(driveIndex, uncIndex) : Math.max(driveIndex, uncIndex)
  if (index < 0) return null
  return line.slice(index).split(/[;,]/, 1)[0].trim().replace(/[)\]}]+$/g, '')
}

function directoryCandidates(raw: string): ClipboardCandidate[] {
  const byValue = new Map<string, ClipboardCandidate>()
  for (const line of raw.split(/\r?\n/)) {
    const extracted = windowsPathFromLine(line)
    if (!extracted) continue
    let value = stripPairedQuotes(extracted)
    let sourceLabel: string | undefined
    let derived = false
    if (/[\\/]goldminer3\.exe$/i.test(value)) {
      value = value.replace(/[\\/]goldminer3\.exe$/i, '')
      sourceLabel = '由 goldminer3.exe 所在目录推导'
      derived = true
    } else if (/[\\/]resources[\\/]app[\\/]gmserv\.json$/i.test(value)) {
      value = value.replace(/[\\/]resources[\\/]app[\\/]gmserv\.json$/i, '')
      sourceLabel = '由 gmserv.json 所在目录推导'
      derived = true
    }
    if (!isWindowsAbsoluteDirectory(value) || byValue.has(value.toLowerCase())) continue
    byValue.set(value.toLowerCase(), {
      id: candidateId('directory', value.toLowerCase()),
      kind: 'directory',
      value,
      displayValue: value,
      sourceLabel,
      derived,
    })
  }
  return [...byValue.values()]
}

function lineCandidates(kind: 'text' | 'identifier', raw: string): ClipboardCandidate[] {
  const values = raw.split(/\r?\n/).map(stripPairedQuotes).filter(Boolean)
  return [...new Set(values)].map((value) => ({
    id: candidateId(kind, value),
    kind,
    value,
    displayValue: value,
  }))
}

function moneyCandidates(raw: string, context: ClipboardParseContext): ClipboardCandidate[] {
  const values: string[] = []
  for (const line of raw.split(/\r?\n/)) {
    const value = normalizeMoneyValue(stripPairedQuotes(line))
    if (value !== null && !connectionValueError({
      kind: 'money',
      value,
      required: true,
      label: context.fieldLabel,
      placeholder: context.placeholder,
      constraints: context.constraints,
    })) values.push(value)
  }
  return [...new Set(values)].map((value) => ({
    id: candidateId('money', value),
    kind: 'money',
    value,
    displayValue: value,
  }))
}

function secretCandidates(raw: string): ClipboardCandidate[] {
  const value = raw.replace(/(?:\r\n|\r|\n)+$/g, '')
  if (!value || /\r|\n/.test(value)) return []
  return [{
    id: `secret-${value.length}`,
    kind: 'secret',
    value,
    displayValue: `•••••••• · ${value.length} 个字符`,
  }]
}

/** 按字段语义提取剪贴板候选；不保留原始剪贴板文本。 */
export function parseConnectionClipboard(
  raw: string,
  context: ClipboardParseContext,
): ClipboardParseResult {
  if (!raw) return { candidates: [], warning: '剪贴板中没有文本内容' }

  let candidates: ClipboardCandidate[]
  if (context.kind === 'endpoint') candidates = endpointCandidates(raw, context)
  else if (context.kind === 'directory') candidates = directoryCandidates(raw)
  else if (context.kind === 'money') candidates = moneyCandidates(raw, context)
  else if (context.kind === 'secret') candidates = secretCandidates(raw)
  else candidates = lineCandidates(context.kind, raw)

  let warning: string | undefined
  if (candidates.length > MAX_CANDIDATES) {
    candidates = candidates.slice(0, MAX_CANDIDATES)
    warning = '候选较多，仅展示前 20 项'
  } else if (candidates.length === 0) {
    warning = context.kind === 'directory'
      ? '未找到有效的 Windows 终端路径'
      : context.kind === 'secret' && /\r|\n/.test(raw.replace(/(?:\r\n|\r|\n)+$/g, ''))
        ? '一次只能粘贴一项内容'
        : '未找到可用于此字段的内容'
  }
  return { candidates, warning }
}

/** 将一次粘贴收敛为报错、直接填入或多值选择，供按钮与系统粘贴共用。 */
export function resolveConnectionClipboardPaste(
  raw: string,
  context: ClipboardParseContext,
): ClipboardPasteResolution {
  const result = parseConnectionClipboard(raw, context)
  if (result.candidates.length === 0) {
    return { action: 'error', warning: result.warning ?? '未找到可用于此字段的内容' }
  }
  if (result.candidates.length === 1) {
    return { action: 'commit', candidate: result.candidates[0], warning: result.warning }
  }
  return { action: 'choose', candidates: result.candidates, warning: result.warning }
}

/** 当前字段明确匹配的候选排在前面，其余保持剪贴板原顺序。 */
export function rankClipboardCandidates(
  candidates: ClipboardCandidate[],
  context: ClipboardParseContext,
): ClipboardCandidate[] {
  const role = context.clipboard?.role
  if (!role) return candidates
  return candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort((left, right) => Number(right.candidate.role === role) - Number(left.candidate.role === role) || left.index - right.index)
    .map(({ candidate }) => candidate)
}
