import { describe, expect, test } from 'bun:test'

import { advancedConfigChanges } from '@/features/init/advancedConfig'
import type { InitValues } from '@/lib/api/init'

const initial: InitValues = {
  sqlalchemy_database_uri: 'sqlite+aiosqlite:///./axile.db',
  exe_err_feishu_key: '',
  environment: 'local',
  app_log_dir: './logs',
  axile_log_rotation: '1 day',
  algorithm_modules: ['pkg.a'],
  algorithm_directories: ['./algorithms'],
}

describe('advancedConfigChanges', () => {
  test('未修改与改回初始值都没有变更', () => {
    expect(advancedConfigChanges(initial, { ...initial })).toEqual([])
    expect(
      advancedConfigChanges(initial, { ...initial, environment: 'local' }),
    ).toEqual([])
  })

  test('按字段汇总标量和数组变更', () => {
    expect(
      advancedConfigChanges(initial, {
        ...initial,
        environment: 'production',
        algorithm_modules: ['pkg.a', 'pkg.b'],
      }),
    ).toEqual(['运行环境', '算法模块'])
  })

  test('数组顺序变化也视为配置变化', () => {
    const current = { ...initial, algorithm_modules: ['pkg.b', 'pkg.a'] }
    expect(advancedConfigChanges(initial, current)).toEqual(['算法模块'])
  })
})
