import { describe, expect, it } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  connectionStaleAt,
  localQueryError,
  type QueryFreshness,
} from './staleData'
import { StaleDataStatus } from './StaleDataStatus'

const NOW = Date.parse('2026-08-26T09:00:00+08:00')
const UPDATED_AT = Date.parse('2026-08-25T18:00:00+08:00')

function query(error: Error | null, stale = true, updatedAt: number | null = UPDATED_AT): QueryFreshness {
  return { error, stale, updatedAt }
}

describe('connection stale presentation', () => {
  it('collapses cached network errors only after the global connection state confirms the outage', () => {
    const networkFailure = query(new TypeError('Failed to fetch'))

    expect(connectionStaleAt(true, [networkFailure])).toBe(UPDATED_AT)
    expect(localQueryError(true, networkFailure)).toBeNull()
    expect(localQueryError(false, networkFailure)).toBe(networkFailure.error)
  })

  it('keeps first-load and endpoint-specific errors local', () => {
    const firstLoadFailure = query(new TypeError('Failed to fetch'), false, null)
    const endpointFailure = query(new Error('HTTP 503'))

    expect(connectionStaleAt(true, [firstLoadFailure, endpointFailure])).toBeNull()
    expect(localQueryError(true, firstLoadFailure)).toBe(firstLoadFailure.error)
    expect(localQueryError(true, endpointFailure)).toBe(endpointFailure.error)
  })

  it('uses the oldest affected timestamp for a combined card status', () => {
    const newer = query(new TypeError('Failed to fetch'), true, UPDATED_AT + 60_000)
    const older = query(new TypeError('Failed to fetch'))

    expect(connectionStaleAt(true, [newer, older])).toBe(UPDATED_AT)
  })
})

describe('StaleDataStatus', () => {
  it('renders a compact freshness statement', () => {
    const html = renderToStaticMarkup(
      createElement(StaleDataStatus, { updatedAt: UPDATED_AT, now: NOW }),
    )

    expect(html).toContain('数据停留在 15 小时前')
    expect(html).toContain('text-warn')
    expect(html).not.toContain('无法连接')
  })

  it('renders no slot while data is current', () => {
    expect(renderToStaticMarkup(createElement(StaleDataStatus, { updatedAt: null }))).toBe('')
  })
})
