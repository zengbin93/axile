import { describe, expect, test } from 'bun:test'

import { initialConnectionDraft, mergedConnectionConfig, sameConnectionConfig } from '@/features/account/connectionConfig'
import type { ChannelAccountField } from '@/types/api'

const fields: ChannelAccountField[] = [
  { name: 'investor_id', label: '投资者号', kind: 'identifier', width: 'half', required: true },
  { name: 'password', label: '密码', kind: 'secret', width: 'full', required: true },
]

const account = {
  account_config: { investor_id: '1001', password: 'old-secret', plugin_extension: true },
}

describe('连接设置敏感字段合并', () => {
  test('初始草稿不把旧密码带入前端输入框', () => {
    expect(initialConnectionDraft(account, fields)).toEqual({ investor_id: '1001', password: '' })
  })

  test('密码留空时保留旧值和未知扩展字段', () => {
    expect(mergedConnectionConfig(account, fields, { investor_id: '1002', password: '' })).toEqual({
      investor_id: '1002', password: 'old-secret', plugin_extension: true,
    })
  })

  test('填入新密码时才替换', () => {
    expect(mergedConnectionConfig(account, fields, { investor_id: '1001', password: 'new-secret' }).password).toBe('new-secret')
  })

  test('对象键顺序不会被误判为改动', () => {
    expect(sameConnectionConfig({ a: 1, nested: { b: 2, a: 1 } }, { nested: { a: 1, b: 2 }, a: 1 })).toBe(true)
  })
})
