import { describe, expect, it } from 'bun:test'

import { gmConnectionError, normalizeGMConnection, switchGMConnectionMode } from './gmConnection'

describe('gmConnectionError', () => {
  it('要求公共凭据与当前连接目标完整', () => {
    expect(gmConnectionError({}, 'terminal')).toBe('请填写账号 ID')
    expect(gmConnectionError({ account_id: 'account' }, 'terminal')).toBe('请填写 Token')
    expect(gmConnectionError({ account_id: 'account', token: 'token' }, 'terminal')).toBe('请填写掘金终端目录')
    expect(gmConnectionError({ account_id: 'account', token: 'token' }, 'service')).toBe('请填写终端 RPC 地址')
  })

  it('只校验当前模式对应的目标字段', () => {
    const config = {
      account_id: 'account',
      token: 'token',
      terminal_path: 'C:\\GoldMiner3',
      serv_addr: '127.0.0.1:7001',
    }
    expect(gmConnectionError(config, 'terminal')).toBeNull()
    expect(gmConnectionError(config, 'service')).toBeNull()
  })
})

describe('normalizeGMConnection', () => {
  it('本地终端模式只提交 terminal_path', () => {
    expect(normalizeGMConnection({
      account_id: ' account ',
      token: ' token ',
      terminal_path: ' C:\\GoldMiner3 ',
      serv_addr: '127.0.0.1:7001',
    }, 'terminal')).toEqual({
      account_id: 'account',
      token: 'token',
      terminal_path: 'C:\\GoldMiner3',
    })
  })

  it('服务地址模式只提交 serv_addr，且不提交空目标', () => {
    expect(normalizeGMConnection({
      account_id: 'account',
      token: 'token',
      terminal_path: 'C:\\GoldMiner3',
      serv_addr: '  ',
    }, 'service')).toEqual({ account_id: 'account', token: 'token' })
  })
})

describe('switchGMConnectionMode', () => {
  it('切换时删除另一模式的互斥字段', () => {
    const config = {
      account_id: 'account',
      token: 'token',
      terminal_path: 'C:\\GoldMiner3',
      serv_addr: '127.0.0.1:7001',
    }
    expect(switchGMConnectionMode(config, 'terminal')).not.toHaveProperty('serv_addr')
    expect(switchGMConnectionMode(config, 'service')).not.toHaveProperty('terminal_path')
  })
})
