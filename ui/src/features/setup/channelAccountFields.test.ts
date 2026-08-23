import { expect, test } from 'bun:test'
import type { ChannelAccountField } from '@/types/api'
import {
  channelAccountFieldVisible,
  updateChannelAccountConfig,
  visibleChannelAccountConfig,
} from './channelAccountFields'

const fields: ChannelAccountField[] = [
  { name: 'account_mode', label: '账户模式', kind: 'select', width: 'full', required: true },
  { name: 'tq_username', label: '天勤账号', kind: 'identifier', width: 'half', required: true },
  {
    name: 'broker_name',
    label: '期货公司',
    kind: 'text',
    width: 'half',
    required: true,
    visible_when: { field: 'account_mode', equals: 'live' },
  },
  {
    name: 'initial_balance',
    label: '初始资金',
    kind: 'money',
    width: 'full',
    required: true,
    visible_when: { field: 'account_mode', equals: 'sim' },
  },
]

test('条件字段只在匹配账户模式时可见', () => {
  expect(channelAccountFieldVisible(fields[2], { account_mode: 'live' })).toBe(true)
  expect(channelAccountFieldVisible(fields[2], { account_mode: 'kq' })).toBe(false)
  expect(channelAccountFieldVisible(fields[3], { account_mode: 'sim' })).toBe(true)
})

test('切换模式时立即移除隐藏字段，提交也只保留可见值', () => {
  const result = updateChannelAccountConfig(fields, {
    account_mode: 'live',
    tq_username: 'user',
    broker_name: 'stale-live-value',
    initial_balance: 123,
  }, 'account_mode', 'kq')

  expect(result).toEqual({ account_mode: 'kq', tq_username: 'user' })
  expect(visibleChannelAccountConfig(fields, result)).toEqual(result)
})

test('任意布尔条件都用 visible_when 清理隐藏字段', () => {
  const binanceFields: ChannelAccountField[] = [
    { name: 'is_testnet', label: '测试网', kind: 'boolean', width: 'half', required: true },
    {
      name: 'assumed_equity',
      label: '兜底权益',
      kind: 'money',
      width: 'half',
      required: false,
      visible_when: { field: 'is_testnet', equals: true },
    },
  ]
  const config = { is_testnet: false, assumed_equity: '-1' }

  expect(channelAccountFieldVisible(binanceFields[1], config)).toBe(false)
  expect(updateChannelAccountConfig(binanceFields, config, 'is_testnet', false)).toEqual({ is_testnet: false })
})
