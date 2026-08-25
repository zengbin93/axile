import { describe, expect, it } from 'bun:test'
import { targetSnapshotIdentity } from './useTargetSnapshot'
import type { TargetWeightSnapshot } from '@/types/api'

const snapshot: TargetWeightSnapshot = {
  weights: { rb2610: 0.5 },
  calculated_at: '2026-08-25T10:00:00',
  source: 'execution',
  execution_id: 'exec-1',
  context_account_id: 1,
}

describe('targetSnapshotIdentity', () => {
  it('同一秒的不同执行仍是不同快照', () => {
    expect(targetSnapshotIdentity(snapshot)).not.toBe(
      targetSnapshotIdentity({ ...snapshot, execution_id: 'exec-2' }),
    )
  })

  it('未计算态没有快照身份', () => {
    expect(targetSnapshotIdentity({ ...snapshot, calculated_at: null })).toBeNull()
  })
})
