import { expect, test } from 'bun:test'
import { executionSelection, executionState } from '@/features/history/executionSelection'
import { selectionQuery } from '@/lib/api/performance'
import type { CostExecutionRow } from '@/lib/api/performance'
import { snapshotPositions, quantityUnit } from '@/features/history/executionEvidenceModel'
import type { ExecutionArtifact } from '@/types/api'

const row = (patch: Partial<CostExecutionRow> = {}): CostExecutionRow => ({ key: '7', record: { id: 7, execution_id: 'exec-7', created_at: '2026-09-08T23:59:00', is_success: 1, raw_result: {} }, noop: true, symbolCount: 0, summary: { value: null, cost: null, lossBp: null, coverage: null, count: 0, covered: 0, amountComplete: true, fees: {}, feeCovered: 0 }, ...patch })
test('单次执行按记录身份筛选，不带日期以保留跨日成交', () => {
  expect(selectionQuery(executionSelection(row()))).toEqual({ record_id: 7 })
  expect(executionSelection(row()).kind).toBe('execution')
})
test('空仓、无交易、未知持仓与失败不混为一种状态', () => {
  expect(executionState(row({ positionCount: 0 }))).toBe('空仓 · 无需交易')
  expect(executionState(row({ positionCount: 2 }))).toBe('持仓不变 · 无需交易')
  expect(executionState(row())).toBe('未交易 · 持仓未知')
  expect(executionState(row({ record: { ...row().record, is_success: 0 }, positionCount: 0 }))).toBe('执行失败')
})
test('缺失和退化快照不当成空仓，完整空数组才是空仓', () => {
  const artifacts = (content: unknown) => [{ artifact_type: 'account_snapshot', content }] as ExecutionArtifact[]
  expect(snapshotPositions([], 'account_snapshot')).toBeNull()
  expect(snapshotPositions(artifacts({ source: 'assumed', account_assets: { positions: [] } }), 'account_snapshot')).toBeNull()
  expect(snapshotPositions(artifacts({ source: 'real', account_assets: { positions: [] } }), 'account_snapshot')).toEqual([])
  expect(snapshotPositions(artifacts({ account_assets: { positions: [{ symbol: 'BTCUSDT' }] } }), 'account_snapshot')).toBeNull()
  expect(quantityUnit({ quantity_kind: 'base_asset', quantity_label: '币', quantity_max_decimals: 6, price_label: '', notional_label: '' }, 'BTCUSDT', 'USDT')).toBe('BTC')
})
