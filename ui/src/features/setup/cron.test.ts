import { describe, it, expect } from 'bun:test'

import {
  buildCronList,
  compileCustom,
  compileScheduleRule,
  describeCron,
  describeRule,
  makeEmptySlot,
  parseTimerIntent,
  resolveCronList,
  timerStateToCronExpr,
  type ScheduleRule,
  type TimerIntent,
} from './cron'

/** 构造一个定时意图，默认无补发（supN=0）便于断言精确值。 */
function intent(patch: Partial<TimerIntent> = {}): TimerIntent {
  return {
    presetIds: [],
    supN: 0,
    supM: 0,
    rawCron: '',
    timerTab: 'quick',
    scheduleRules: [],
    selectedRuleId: '',
    customCronOn: false,
    ...patch,
  }
}

function rule(patch: Partial<ScheduleRule> = {}): ScheduleRule {
  return {
    id: 'r1',
    freq: 'd1',
    time: '08:00',
    days: [],
    anchor: 'open',
    draft: false,
    ...patch,
  }
}

describe('compileCustom · continuous', () => {
  it('日线锚定 08:00（无补发）', () => {
    expect(compileCustom('continuous', 'd1', 'open', 0, 0)).toEqual(['0 8 * * *'])
  })

  it('m60 走每小时、m120 走 */2、m240 走 */4', () => {
    expect(compileCustom('continuous', 'm60', 'open', 0, 0)).toEqual(['0 * * * *'])
    expect(compileCustom('continuous', 'm120', 'open', 0, 0)).toEqual(['0 */2 * * *'])
    expect(compileCustom('continuous', 'm240', 'open', 0, 0)).toEqual(['0 */4 * * *'])
  })

  it('m15 叠加补发（补 2 次每隔 1 分）铺满每 15 分的 0/1/2 偏移', () => {
    expect(compileCustom('continuous', 'm15', 'open', 2, 1)).toEqual([
      '0,1,2,15,16,17,30,31,32,45,46,47 * * * *',
    ])
  })
})

describe('compileCustom · 时段市场按锚点落点', () => {
  it('A股日线 open=09:30 / close=14:50', () => {
    expect(compileCustom('cn_stock', 'd1', 'open', 0, 0)).toEqual(['30 9 * * *'])
    expect(compileCustom('cn_stock', 'd1', 'close', 0, 0)).toEqual(['50 14 * * *'])
  })

  it('CTP 日线 close=15:00', () => {
    expect(compileCustom('cn_futures', 'd1', 'close', 0, 0)).toEqual(['0 15 * * *'])
  })

  it('m240 与日线同锚点', () => {
    expect(compileCustom('cn_stock', 'm240', 'close', 0, 0)).toEqual(['50 14 * * *'])
  })

  it('A股 m120 用时段表 11:30/15:00（含 m120，验证 SESS 已补齐）', () => {
    expect(compileCustom('cn_stock', 'm120', 'open', 0, 0)).toEqual([
      '0 15 * * *',
      '30 11 * * *',
    ])
  })
})

describe('compileScheduleRule · 可调时刻与周几', () => {
  it('连续交易每天 09:30', () => {
    expect(compileScheduleRule('continuous', rule({ time: '09:30' }), 0, 0)).toEqual(['30 9 * * *'])
  })

  it('显式选择周一至周五时转换为 APScheduler 编号', () => {
    expect(compileScheduleRule('continuous', rule({ time: '08:00', days: [1, 2, 3, 4, 5] }), 0, 0)).toEqual([
      '0 8 * * 0,1,2,3,4',
    ])
  })

  it('显式选择周日时转换为 APScheduler 的 6', () => {
    expect(compileScheduleRule('continuous', rule({ days: [0] }), 0, 0)).toEqual(['0 8 * * 6'])
  })

  it('空槽不编译', () => {
    expect(compileScheduleRule('continuous', rule({ draft: true, time: '' }), 0, 0)).toEqual([])
  })

  it('多条规则拼接（忽略空槽）', () => {
    const t = intent({
      timerTab: 'advanced',
      scheduleRules: [rule({ time: '08:00' }), rule({ id: 'r2', time: '20:00' }), makeEmptySlot(rule())],
    })
    expect(resolveCronList('continuous', t)).toEqual(['0 8 * * *', '0 20 * * *'])
  })
})

describe('resolveCronList · 优先级', () => {
  it('自定义模式开 + rawCron 最高优先', () => {
    const t = intent({
      customCronOn: true,
      rawCron: '5 9 * * 1-5 | 50 14 * * 1-5',
      timerTab: 'advanced',
      scheduleRules: [rule()],
      presetIds: ['d1'],
    })
    expect(resolveCronList('continuous', t)).toEqual(['5 9 * * 1-5', '50 14 * * 1-5'])
  })

  it('兼容旧 customOn → compileCustom', () => {
    const t = intent({ customOn: true, customFreq: 'd1', customAnchor: 'open' })
    expect(resolveCronList('continuous', t)).toEqual(['0 8 * * *'])
  })

  it('快捷 tab → 预设编译', () => {
    const t = intent({ presetIds: ['d1'], timerTab: 'quick' })
    expect(resolveCronList('continuous', t)).toEqual(['0 8 * * *'])
  })

  it('空意图返回空数组', () => {
    expect(resolveCronList('continuous', intent())).toEqual([])
  })

  it('仅 rawCron 无 tab（编辑页）仍走表达式', () => {
    const t = intent({ rawCron: '0 9 * * *', timerTab: undefined })
    expect(resolveCronList('continuous', t)).toEqual(['0 9 * * *'])
  })
})

describe('buildCronList · 补发放大偏移', () => {
  it('连续交易每 15 分 + 补 2 次每隔 1 分', () => {
    expect(buildCronList('continuous', ['m15'], 2, 1)).toEqual([
      '0,1,2,15,16,17,30,31,32,45,46,47 * * * *',
    ])
  })

  it('A股多选预设拼接多条规则（开盘+临收）', () => {
    expect(buildCronList('cn_stock', ['open', 'close'], 0, 0)).toEqual(['30 9 * * *', '50 14 * * *'])
  })
})

describe('describeRule', () => {
  it('空槽显示未完成', () => {
    expect(describeRule(rule({ draft: true, time: '' }))).toBe('未完成')
  })

  it('每天带时刻', () => {
    expect(describeRule(rule({ time: '20:00' }))).toBe('每天 20:00')
  })
})

describe('describeCron · cron 反解人话', () => {
  it('每 15 分钟 + 补发 2 次（与图示同款展开）', () => {
    expect(describeCron('continuous', '0,1,2,15,16,17,30,31,32,45,46,47 * * * *')).toBe('每 15 分钟 · 补发 2 次')
  })

  it('每天带时间、无补发不加后缀', () => {
    expect(describeCron('continuous', buildCronList('continuous', ['d1'], 0, 0).join(' | '))).toBe('每天 08:00')
  })

  it('每小时 / 每 4 小时不误拼机器味 sub', () => {
    expect(describeCron('continuous', '0 * * * *')).toBe('每小时')
    expect(describeCron('continuous', '0 */4 * * *')).toBe('每 4 小时')
  })

  it('分钟乱序 / 重复仍能归一识别', () => {
    expect(describeCron('continuous', '45,0,30,15,15 * * * *')).toBe('每 15 分钟')
  })

  it('时段市场预设带交易日时间', () => {
    expect(describeCron('cn_stock', buildCronList('cn_stock', ['open'], 0, 0).join(' | '))).toBe('每交易日 · 开盘 09:30')
  })

  it('多选 / 裸 cron 等非单预设组合返回 null', () => {
    expect(describeCron('continuous', '7 3 * * *')).toBeNull()
    expect(describeCron('cn_stock', buildCronList('cn_stock', ['open', 'close'], 0, 0).join(' | '))).toBeNull()
  })

  it('空表达式返回 null', () => {
    expect(describeCron('continuous', '')).toBeNull()
  })
})

describe('parseTimerIntent · 编辑页回填', () => {
  it('空 cron → 关自动 + 默认快捷', () => {
    const s = parseTimerIntent('continuous', '')
    expect(s.autoOn).toBe(false)
    expect(s.timerTab).toBe('quick')
    expect(s.presetIds).toEqual(['d1'])
    expect(timerStateToCronExpr('continuous', s)).toBe('')
  })

  it('每 15 分 + 补 2 次 → 快捷预设（编辑页裸 cron 同款）', () => {
    const s = parseTimerIntent('continuous', '0,1,2,15,16,17,30,31,32,45,46,47 * * * *')
    expect(s.autoOn).toBe(true)
    expect(s.timerTab).toBe('quick')
    expect(s.presetIds).toEqual(['m15'])
    expect(s.supN).toBe(2)
    expect(s.supM).toBe(1)
    expect(s.customCronOn).toBe(false)
    expect(timerStateToCronExpr('continuous', s)).toBe('0,1,2,15,16,17,30,31,32,45,46,47 * * * *')
  })

  it('单一非预设日频 → 高级 d1 规则', () => {
    const s = parseTimerIntent('continuous', '0 21 * * *')
    expect(s.autoOn).toBe(true)
    expect(s.timerTab).toBe('advanced')
    expect(s.customCronOn).toBe(false)
    expect(s.scheduleRules).toHaveLength(1)
    expect(s.scheduleRules![0]!.freq).toBe('d1')
    expect(s.scheduleRules![0]!.time).toBe('21:00')
  })

  it('多条日频 → 高级多规则', () => {
    const s = parseTimerIntent('continuous', '0 8 * * * | 0 20 * * *')
    expect(s.timerTab).toBe('advanced')
    expect(s.customCronOn).toBe(false)
    expect(s.scheduleRules).toHaveLength(2)
    expect(s.scheduleRules!.map((r) => r.time).sort()).toEqual(['08:00', '20:00'])
  })

  it('无法结构化 → 高级自定义模式', () => {
    const s = parseTimerIntent('continuous', '7 3 * * * | */5 * * * *')
    expect(s.timerTab).toBe('advanced')
    expect(s.customCronOn).toBe(true)
    expect(s.rawCron).toContain('7 3 * * *')
  })
})
