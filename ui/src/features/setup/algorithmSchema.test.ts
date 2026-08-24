import { describe, expect, it } from 'bun:test'

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
