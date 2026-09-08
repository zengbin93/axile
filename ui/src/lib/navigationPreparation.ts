import { parsePath, resolvePath, type To } from 'react-router'

/** 与 Router 的相对路由解析一致：每个 .. 消耗一个贡献路径的路由。 */
export function navigationPath(to: To, pathname: string, routePaths: string[], relative?: 'path' | 'route') {
  const parsed = typeof to === 'string' ? parsePath(to) : { ...to }
  let base = pathname
  if (parsed.pathname && relative !== 'path') {
    const segments = parsed.pathname.split('/')
    let index = routePaths.length - 1
    while (segments[0] === '..') { segments.shift(); index-- }
    base = routePaths[index] ?? '/'
    parsed.pathname = segments.join('/')
  }
  return resolvePath(parsed, base).pathname
}

export function isCurrentTabClick(event: {
  defaultPrevented: boolean; button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean
}, target?: string, reloadDocument?: boolean, download?: unknown) {
  return !event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
    && (!target || target === '_self') && !reloadDocument && download == null
}
