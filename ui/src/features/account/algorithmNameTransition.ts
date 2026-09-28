import type { AlgorithmSlot } from '@/types/api'
import type { Account } from '@/types/api'

/** 同一路径的两个入口由点击意图区分；返程沿用最后进入的槽位。 */
const activeSlots = new Map<number, AlgorithmSlot>()
const accountPreviews = new Map<number, Account>()

export function writeAlgorithmAccountPreview(accountId: number, account: Account): void {
  accountPreviews.set(accountId, account)
}

export function readAlgorithmAccountPreview(accountId: number): Account | null {
  return accountPreviews.get(accountId) ?? null
}

export function selectAlgorithmTransitionSlot(accountId: number, slot: AlgorithmSlot): void {
  activeSlots.set(accountId, slot)
}

export function algorithmTransitionSlot(accountId: number): AlgorithmSlot | undefined {
  return activeSlots.get(accountId)
}
