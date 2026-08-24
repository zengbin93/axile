import { describe, it, expect } from 'bun:test'

import {
  defaultAlgorithm,
  describeAlgorithmRef,
  describeSingleMakerParams,
  describeTargetPosParams,
  effectiveTargetPosParams,
  effectiveSingleMakerParams,
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

  it('拒绝非法枚举、非整数追单次数和非数字等待时间', () => {
    expect(validateAlgorithmParams({ price_strategy: 'MARKET' })).toContain('price_strategy')
    expect(validateAlgorithmParams({ offset_priority: '开平' })).toContain('offset_priority')
    expect(validateAlgorithmParams({ on_missing_book: 'fallback' })).toContain('on_missing_book')
    expect(validateAlgorithmParams({ max_wait_seconds: '60' })).toContain('必须是数字')
    expect(validateAlgorithmParams({ chase_enabled: true, max_chase_count: 1.5 })).toContain('整数')
  })
})

describe('resolveAlgorithm · 省成本预设', () => {
  it('产出的 params 通过后端约束校验', () => {
    expect(validateAlgorithmParams(resolveAlgorithm('save', 'crypto').params)).toBeNull()
  })
})

describe('intentFromParams · 意图反推（镜像 resolveAlgorithm）', () => {
  it('三档 params 都能反推回原意图', () => {
    for (const market of ['crypto', 'ashare'] as const) {
      for (const intent of ['save', 'fill', 'balance'] as const) {
        expect(intentFromParams(resolveAlgorithm(intent, market).params)).toBe(intent)
      }
    }
  })

  it('无法匹配的 params 返回 null', () => {
    expect(intentFromParams({ price_strategy: 'ACTIVE', chase_enabled: true })).toBeNull()
    expect(intentFromParams({})).toBeNull()
  })

  it('缺省字段按后端默认值解释', () => {
    expect(
      intentFromParams({
        price_strategy: 'ACTIVE',
        max_wait_seconds: 30,
        chase_enabled: false,
      }),
    ).toBe('fill')
    expect(effectiveSingleMakerParams({}).on_missing_book).toBe('skip')
  })

  it('关闭追单时忽略未生效的追单细项', () => {
    const fill = resolveAlgorithm('fill', 'crypto').params
    expect(intentFromParams({ ...fill, max_chase_count: 999, chase_interval: 0 })).toBe('fill')
  })

  it('任一生效参数、盘口策略或未知参数不同都视为自定义', () => {
    const balance = resolveAlgorithm('balance', 'crypto').params
    expect(intentFromParams({ ...balance, max_wait_seconds: 90 })).toBeNull()
    expect(intentFromParams({ ...balance, on_missing_book: 'active' })).toBeNull()
    expect(intentFromParams({ ...balance, plugin_option: true })).toBeNull()
  })
})

describe('describeSingleMakerParams · 当前执行摘要', () => {
  it('区分追单与不追单', () => {
    expect(describeSingleMakerParams(resolveAlgorithm('balance', 'crypto').params)).toBe(
      '被动挂单 · 等待 60 秒 · 最多追单 5 次',
    )
    expect(describeSingleMakerParams(resolveAlgorithm('fill', 'crypto').params)).toBe(
      '主动成交 · 等待 30 秒 · 不追单',
    )
  })

  it('非默认盘口兜底追加到摘要，自定义算法引用明确标记', () => {
    const params = { ...resolveAlgorithm('balance', 'crypto').params, on_missing_book: 'market' }
    expect(describeSingleMakerParams(params)).toContain('盘口缺失时直接市价成交')
    expect(describeAlgorithmRef({ method: 'SINGLE-MAKER', params }, 'crypto')).toBe('挂单追单（自定义）')
  })

  it('TARGET-POS-TASK 摘要显示有效等待与追单参数', () => {
    expect(describeTargetPosParams({})).toBe('被动挂单 · 等待 60 秒 · 不追单')
    expect(describeAlgorithmRef(resolveAlgorithm('balance', 'ctp'), 'ctp')).toBe(
      '被动挂单 · 等待 60 秒 · 最多追单 5 次',
    )
  })
})

describe('effectiveTargetPosParams · 目标持仓默认参数', () => {
  it('为空参数补齐后端的七个默认字段，并允许局部覆盖', () => {
    const effective = effectiveTargetPosParams({ chase_enabled: true, plugin_option: 'keep' })

    expect(effective).toEqual({
      price_strategy: 'PASSIVE',
      offset_priority: '昨今',
      max_wait_seconds: 60,
      chase_enabled: true,
      chase_ticks: 1,
      max_chase_count: 5,
      chase_interval: 5,
      plugin_option: 'keep',
    })
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

  it('ctp 清仓保存完整参数并默认主动吃单', () => {
    expect(emptyAlgorithm('ctp').params).toEqual({
      price_strategy: 'ACTIVE',
      offset_priority: '昨今',
      max_wait_seconds: 60,
      chase_enabled: false,
      chase_ticks: 1,
      max_chase_count: 5,
      chase_interval: 5,
    })
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

  it('TARGET-POS-TASK 种子包含完整且合法的参数', () => {
    const params = seedParams('TARGET-POS-TASK', 'ctp')

    expect(params).toEqual(effectiveTargetPosParams({}))
    expect(validateAlgorithmParams(params)).toBeNull()
  })
})
