import { describe, expect, test } from 'bun:test'

import { initialConnectionDraft, mergedConnectionConfig, sameConnectionConfig } from '@/features/account/connectionConfig'
import type { ChannelAccountField } from '@/types/api'

const fields: ChannelAccountField[] = [
  { name: 'investor_id', label: '投资者号', kind: 'identifier', width: 'half', required: true },
  { name: 'password', label: '密码', kind: 'secret', width: 'full', required: true },
]

const account = { account_configured: true }

describe('连接设置敏感字段不回显', () => {
  test('初始草稿不包含任何已保存的连接值', () => {
    expect(initialConnectionDraft(account, fields)).toEqual({ investor_id: '', password: '' })
  })

  test('密码留空时不把旧值带回网络请求', () => {
    expect(mergedConnectionConfig(account, fields, { investor_id: '1002', password: '' })).toEqual({ investor_id: '1002' })
  })

  test('填入新密码时才替换', () => {
    expect(mergedConnectionConfig(account, fields, { investor_id: '1001', password: 'new-secret' }).password).toBe('new-secret')
  })

  test('对象键顺序不会被误判为改动', () => {
    expect(sameConnectionConfig({ a: 1, nested: { b: 2, a: 1 } }, { nested: { a: 1, b: 2 }, a: 1 })).toBe(true)
  })
})

test('修改密钥保留测试网及已关闭的连接开关', () => {
  const fields: ChannelAccountField[] = [
    { name: 'network', label: '网络', kind: 'select', width: 'full', required: true, default: 'mainnet' },
    { name: 'websocket_enabled', label: 'WebSocket', kind: 'boolean', width: 'full', required: false, default: true },
    { name: 'password', label: '密码', kind: 'secret', width: 'full', required: true },
  ]
  const account = { account_configured: true, connection_values: { network: 'testnet', websocket_enabled: false, password: 'must-not-display' } }
  const draft = initialConnectionDraft(account, fields)
  expect(draft).toEqual({ network: 'testnet', websocket_enabled: false, password: '' })
  expect(mergedConnectionConfig(account, fields, { ...draft, password: 'new' })).toEqual({ network: 'testnet', websocket_enabled: false, password: 'new' })
})
