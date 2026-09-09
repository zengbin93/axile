import { describe, expect, it, test } from 'bun:test'

import {
  algorithmSchemaDefaults,
  algorithmSchemaFields,
  validateAlgorithmSchemaParams,
} from './algorithmSchema'

const schema: Record<string, unknown> = {
  type: 'object',
  properties: {
    pace: { type: 'number', title: '执行节奏', default: 0.5, exclusiveMinimum: 0, maximum: 1 },
    rounds: { type: 'integer', title: '轮次', default: 3, minimum: 1 },
    mode: { type: 'string', title: '模式', enum: ['steady', 'fast'], default: 'steady' },
    enabled: { type: 'boolean', title: '启用', default: true },
  },
}

describe('algorithmSchemaFields', () => {
  it('解析扁平 primitive 字段并提取默认值', () => {
    const fields = algorithmSchemaFields(schema)
    expect(fields?.map((field) => field.name)).toEqual(['pace', 'rounds', 'mode', 'enabled'])
    expect(algorithmSchemaDefaults(fields ?? [])).toEqual({ pace: 0.5, rounds: 3, mode: 'steady', enabled: true })
  })

  it('嵌套对象和数组不做不完整的结构化编辑', () => {
    expect(algorithmSchemaFields({ type: 'object', properties: { nested: { type: 'object' } } })).toBeNull()
    expect(algorithmSchemaFields({ type: 'object', properties: { values: { type: 'array' } } })).toBeNull()
  })
})

describe('validateAlgorithmSchemaParams', () => {
  it('校验类型、枚举和数值边界', () => {
    expect(validateAlgorithmSchemaParams({ pace: 0, rounds: 3 }, schema)).toContain('大于 0')
    expect(validateAlgorithmSchemaParams({ pace: 0.5, rounds: 1.5 }, schema)).toContain('整数')
    expect(validateAlgorithmSchemaParams({ mode: 'unknown' }, schema)).toContain('可选范围')
    expect(validateAlgorithmSchemaParams({ enabled: 'yes' }, schema)).toContain('布尔')
    expect(validateAlgorithmSchemaParams({ pace: 0.5, rounds: 3, mode: 'fast', enabled: false }, schema)).toBeNull()
  })
})

// 显示扩展不改变持久化的小数参与率，也不引入前端算法文案。
test('服务端百分比与枚举显示元数据', async () => {
  const { algorithmNumericDisplay, algorithmFieldOptions } = await import('./algorithmSchema')
  const display = algorithmNumericDisplay({ type: 'number', exclusiveMinimum: 0, maximum: 1, 'x-display-scale': 100, 'x-display-step': 0.01, 'x-unit': '%' }, 0.1)
  expect(display.value).toBe(10)
  expect(display.max).toBe(100)
  expect(display.exclusiveMin).toBe(true)
  expect(12.5 / display.scale).toBe(0.125)
  expect(algorithmFieldOptions({ type: 'string', enum: ['ACTIVE'], 'x-enum-labels': { ACTIVE: '后端新名称' } })).toEqual([{ value: 'ACTIVE', label: '后端新名称' }])
})
