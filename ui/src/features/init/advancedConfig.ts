import type { InitValues } from '@/lib/api/init'

const ADVANCED_KEYS = [
  ['sqlalchemy_database_uri', '数据库地址'],
  ['environment', '运行环境'],
  ['app_log_dir', '日志目录'],
  ['axile_log_rotation', '日志滚动'],
  ['algorithm_directories', '用户算法目录'],
  ['algorithm_modules', '算法模块'],
] as const

function sameStrings(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  )
}

/** 高级配置草稿相对初始值的可读变更摘要。 */
export function advancedConfigChanges(
  initial: InitValues,
  current: InitValues,
): string[] {
  return ADVANCED_KEYS.flatMap(([key, label]) => {
    const before = initial[key]
    const after = current[key]
    const equal =
      Array.isArray(before) && Array.isArray(after)
        ? sameStrings(before, after)
        : before === after
    return equal ? [] : [label]
  })
}
