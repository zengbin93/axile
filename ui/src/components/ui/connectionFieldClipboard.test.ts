import { describe, expect, it } from 'bun:test'

import {
  clipboardReadFailureMessage,
  parseConnectionClipboard,
  rankClipboardCandidates,
  resolveConnectionClipboardPaste,
  type ClipboardParseContext,
} from './connectionFieldClipboard'

const endpointContext: ClipboardParseContext = {
  kind: 'endpoint',
  fieldLabel: '交易前置',
  clipboard: { role: 'trading', group: 'fronts' },
  constraints: {
    endpoint: { scheme: 'required', allowed_schemes: ['tcp'], port: 'required', allow_path: false },
  },
}

const genericEndpointContext: ClipboardParseContext = {
  kind: 'endpoint',
  fieldLabel: '地址',
  constraints: {
    endpoint: {
      scheme: 'optional',
      allowed_schemes: ['tcp', 'http', 'https', 'ftp', 'ws', 'wss'],
      port: 'optional',
      allow_path: true,
    },
  },
}

describe('parseConnectionClipboard', () => {
  it('从配置和日志中提取、标注并去重地址', () => {
    const result = parseConnectionClipboard([
      '交易前置=tcp://180.168.1.1:10130',
      '行情前置: tcp://180.168.1.1:10131;',
      'proxy=http://127.0.0.1:7890/path?q=1',
      'again tcp://180.168.1.1:10130',
      'rpc=[::1]:7001',
      'bad=host:70000',
    ].join('\n'), genericEndpointContext)

    expect(result.candidates.map((candidate) => candidate.value)).toEqual([
      'tcp://180.168.1.1:10130',
      'tcp://180.168.1.1:10131',
      'http://127.0.0.1:7890/path?q=1',
      '[::1]:7001',
    ])
    expect(result.candidates.map((candidate) => candidate.role)).toEqual([
      'trading', 'market-data', 'proxy', 'rpc',
    ])
  })

  it('按当前字段推荐排序但保留同组顺序', () => {
    const candidates = parseConnectionClipboard(
      '行情前置=tcp://md:2\n交易前置=tcp://td:1\ntcp://other:3',
      endpointContext,
    ).candidates
    expect(rankClipboardCandidates(candidates, endpointContext).map((candidate) => candidate.value)).toEqual([
      'tcp://td:1', 'tcp://md:2', 'tcp://other:3',
    ])
    expect(endpointContext.clipboard?.role).toBe('trading')
  })

  it('同一行配置按离地址最近的键标注角色', () => {
    const result = parseConnectionClipboard(
      '{"td_front":"tcp://td:1","md_front":"tcp://md:2"}',
      endpointContext,
    )
    expect(result.candidates.map((candidate) => candidate.role)).toEqual(['trading', 'market-data'])
  })

  it('只接受 Windows 绝对目录并推导 GM 根目录', () => {
    const result = parseConnectionClipboard([
      '"C:\\Program Files\\GoldMiner3\\goldminer3.exe"',
      'config=C:/GM/resources/app/gmserv.json',
      '\\\\server\\share\\GoldMiner3',
      '/opt/goldminer3',
      '.\\GoldMiner3',
    ].join('\n'), { kind: 'directory', fieldLabel: '掘金终端目录' })

    expect(result.candidates.map((candidate) => candidate.value)).toEqual([
      'C:\\Program Files\\GoldMiner3',
      'C:/GM',
      '\\\\server\\share\\GoldMiner3',
    ])
    expect(result.candidates.slice(0, 2).every((candidate) => candidate.derived)).toBe(true)
  })

  it('拒绝 POSIX 和相对目录', () => {
    const result = parseConnectionClipboard('/opt/goldminer3\n../GoldMiner3', {
      kind: 'directory', fieldLabel: '掘金终端目录',
    })
    expect(result.candidates).toEqual([])
    expect(result.warning).toBe('未找到有效的 Windows 终端路径')
  })

  it('整理文本、标识符和金额的逐行候选', () => {
    expect(parseConnectionClipboard(' first \n"second"', {
      kind: 'text', fieldLabel: '名称',
    }).candidates.map((candidate) => candidate.value)).toEqual(['first', 'second'])
    expect(parseConnectionClipboard('10,000,000\n-2.5', {
      kind: 'money', fieldLabel: '初始资金',
    }).candidates.map((candidate) => candidate.value)).toEqual(['10000000', '-2.5'])
  })

  it('密钥只生成一个遮罩候选并拒绝有效多行', () => {
    const context: ClipboardParseContext = { kind: 'secret', fieldLabel: '密码' }
    const single = parseConnectionClipboard(' key with spaces \r\n', context)
    expect(single.candidates[0].value).toBe(' key with spaces ')
    expect(single.candidates[0].displayValue).not.toContain('key with spaces')
    expect(parseConnectionClipboard('first\nsecond', context).warning).toBe('一次只能粘贴一项内容')
  })

  it('候选超过上限时截断', () => {
    const raw = Array.from({ length: 25 }, (_, index) => `value-${index}`).join('\n')
    const result = parseConnectionClipboard(raw, { kind: 'identifier', fieldLabel: 'ID' })
    expect(result.candidates).toHaveLength(20)
    expect(result.warning).toBe('候选较多，仅展示前 20 项')
  })
})

describe('resolveConnectionClipboardPaste', () => {
  it('零项只返回错误，不提供可写入值', () => {
    expect(resolveConnectionClipboardPaste('not-an-endpoint', endpointContext)).toEqual({
      action: 'error',
      warning: '未找到可用于此字段的内容',
    })
  })

  it('单项直接提交，多项建立本次粘贴选择', () => {
    const single = resolveConnectionClipboardPaste('tcp://host:10130', endpointContext)
    expect(single.action).toBe('commit')
    if (single.action === 'commit') expect(single.candidate.value).toBe('tcp://host:10130')

    const multiple = resolveConnectionClipboardPaste('tcp://host:10130\ntcp://host:10131', endpointContext)
    expect(multiple.action).toBe('choose')
    if (multiple.action === 'choose') {
      expect(multiple.candidates.map((candidate) => candidate.value)).toEqual([
        'tcp://host:10130',
        'tcp://host:10131',
      ])
    }
  })

  it('非法金额不会回退为原文写入', () => {
    const resolution = resolveConnectionClipboardPaste('人民币 100 万', {
      kind: 'money', fieldLabel: '初始资金',
    })
    expect(resolution.action).toBe('error')
  })
})

describe('clipboardReadFailureMessage', () => {
  it('不向用户暴露浏览器权限异常原文', () => {
    const message = clipboardReadFailureMessage()
    expect(message).toBe('无法读取剪贴板，请使用 Ctrl/Cmd+V 或系统粘贴')
    expect(message).not.toContain('permission')
    expect(message).not.toContain('readText')
  })
})
