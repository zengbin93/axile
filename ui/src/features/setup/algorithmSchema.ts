export interface AlgorithmParamSchema {
  type: 'string' | 'integer' | 'number' | 'boolean'
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  multipleOf?: number
}

export interface AlgorithmSchemaField {
  name: string
  schema: AlgorithmParamSchema
  required: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function parseParamSchema(value: unknown): AlgorithmParamSchema | null {
  if (!isRecord(value)) return null
  if (!['string', 'integer', 'number', 'boolean'].includes(String(value.type))) return null
  if (value.enum !== undefined && !Array.isArray(value.enum)) return null
  return value as unknown as AlgorithmParamSchema
}

/** 将 Pydantic 生成的扁平 JSON Schema 解析为可结构化编辑的字段。 */
export function algorithmSchemaFields(schema: Record<string, unknown>): AlgorithmSchemaField[] | null {
  if (schema.type !== 'object' || !isRecord(schema.properties)) return null
  const required = new Set(Array.isArray(schema.required) ? schema.required.filter((key): key is string => typeof key === 'string') : [])
  const fields: AlgorithmSchemaField[] = []
  for (const [name, raw] of Object.entries(schema.properties)) {
    const parsed = parseParamSchema(raw)
    if (!parsed) return null
    fields.push({ name, schema: parsed, required: required.has(name) })
  }
  return fields
}

/** 从 schema 提取字段默认值，供运行时 default_params 缺失时补齐。 */
export function algorithmSchemaDefaults(fields: AlgorithmSchemaField[]): Record<string, unknown> {
  return Object.fromEntries(
    fields.filter((field) => field.schema.default !== undefined).map((field) => [field.name, field.schema.default]),
  )
}

/** 按 JSON Schema 的 primitive 约束校验算法参数。 */
export function validateAlgorithmSchemaParams(
  params: Record<string, unknown>,
  schema: Record<string, unknown>,
): string | null {
  const fields = algorithmSchemaFields(schema)
  if (!fields) return null
  for (const field of fields) {
    const value = params[field.name]
    if (value === undefined) {
      if (field.required && field.schema.default === undefined) return `${field.schema.title || field.name}为必填参数`
      continue
    }
    const label = field.schema.title || field.name
    if (field.schema.type === 'boolean' && typeof value !== 'boolean') return `${label}必须是布尔值`
    if (field.schema.type === 'string' && typeof value !== 'string') return `${label}必须是字符串`
    if (field.schema.type === 'integer' && (typeof value !== 'number' || !Number.isInteger(value))) {
      return `${label}必须是整数`
    }
    if (field.schema.type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) {
      return `${label}必须是数字`
    }
    if (field.schema.enum && !field.schema.enum.includes(value)) return `${label}不在可选范围内`
    if (typeof value !== 'number') continue
    if (field.schema.minimum !== undefined && value < field.schema.minimum) return `${label}不能小于 ${field.schema.minimum}`
    if (field.schema.maximum !== undefined && value > field.schema.maximum) return `${label}不能大于 ${field.schema.maximum}`
    if (field.schema.exclusiveMinimum !== undefined && value <= field.schema.exclusiveMinimum) {
      return `${label}必须大于 ${field.schema.exclusiveMinimum}`
    }
    if (field.schema.exclusiveMaximum !== undefined && value >= field.schema.exclusiveMaximum) {
      return `${label}必须小于 ${field.schema.exclusiveMaximum}`
    }
    if (field.schema.multipleOf !== undefined && Math.abs(value / field.schema.multipleOf - Math.round(value / field.schema.multipleOf)) > 1e-9) {
      return `${label}必须按 ${field.schema.multipleOf} 递增`
    }
  }
  return null
}
