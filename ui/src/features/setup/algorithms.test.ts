import { describe, it, expect } from 'bun:test'

import {
  defaultAlgorithm,
  emptyAlgorithm,
  intentFromParams,
  resolveAlgorithm,
  seedParams,
  validateAlgorithmParams,
} from './algorithms'

describe('validateAlgorithmParams', () => {
  it('拒绝 max_wait_seconds=0（越界）', () => {
    expect(validateAlgorithmParams({ max_wait_seconds: 0 })).toContain('max_wait_seconds')
  })

  it('拒绝启用追单时 max_chase_count 超上限', () => {
    const err = validateAlgorithmParams({ chase_enabled: true, max_chase_count: 99, chase_interval: 5 })
    expect(err).toContain('max_chase_count')
  })

  it('拒绝追单总时长超过 600s', () => {
    const err = validateAlgorithmParams({ chase_enabled: true, max_chase_count: 40, chase_interval: 20 })
    expect(err).toContain('600')
  })

  it('合法参数返回 null', () => {
    expect(
      validateAlgorithmParams({ max_wait_seconds: 3600, chase_enabled: true, max_chase_count: 50, chase_interval: 5 }),
    ).toBeNull()
  })

  it('未启用追单时不校验追单族', () => {
    expect(validateAlgorithmParams({ chase_enabled: false, max_chase_count: 999 })).toBeNull()
  })
})

describe('resolveAlgorithm · 省成本预设', () => {
  it('产出的 params 通过后端约束校验', () => {
    expect(validateAlgorithmParams(resolveAlgorithm('save', 'crypto').params)).toBeNull()
  })
})

describe('intentFromParams · 意图反推（镜像 resolveAlgorithm）', () => {
  it('三档 params 都能反推回原意图', () => {
    for (const market of ['crypto', 'ctp', 'ashare'] as const) {
      for (const intent of ['save', 'fill', 'balance'] as const) {
        expect(intentFromParams(resolveAlgorithm(intent, market).params)).toBe(intent)
      }
    }
  })

  it('无法匹配的 params 返回 null', () => {
    expect(intentFromParams({ price_strategy: 'ACTIVE', chase_enabled: true })).toBeNull()
    expect(intentFromParams({})).toBeNull()
  })
})

describe('defaultAlgorithm · 槽位默认', () => {
  it('主交易槽为 SINGLE-MAKER（crypto）/ TARGET-POS-TASK（ctp）', () => {
    expect(defaultAlgorithm('crypto', 'trade').method).toBe('SINGLE-MAKER')
    expect(defaultAlgorithm('ctp', 'trade').method).toBe('TARGET-POS-TASK')
  })

  it('通用加密市场清仓槽使用主动成交算法', () => {
    const ref = defaultAlgorithm('crypto', 'empty')
    expect(ref.method).toBe('SINGLE-MAKER')
    expect('prefer_market' in ref.params).toBe(false)
  })
})

describe('emptyAlgorithm · 不再发送废弃键', () => {
  it('crypto 清仓只保留通用主动价格策略', () => {
    expect(emptyAlgorithm('crypto').params).toEqual({ price_strategy: 'ACTIVE' })
  })
})

describe('seedParams · 切换算法的合法种子参数', () => {
  it('TWAP 种子含 total_duration / slices', () => {
    const p = seedParams('TWAP', 'crypto')
    expect(p.total_duration).toBe(300)
    expect(p.slices).toBe(10)
  })

  it('POV 种子参与率落在 (0,1]', () => {
    const p = seedParams('POV', 'crypto')
    expect((p.participation_rate as number) > 0 && (p.participation_rate as number) <= 1).toBe(true)
  })

  it('SINGLE-MAKER 种子通过后端约束校验', () => {
    expect(validateAlgorithmParams(seedParams('SINGLE-MAKER', 'crypto'))).toBeNull()
  })
})
