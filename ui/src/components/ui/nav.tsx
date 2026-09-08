import { useCallback, useContext, type RefAttributes } from 'react'
import {
  Link as RouterLink,
  useNavigate as useRouterNavigate,
  useLocation,
  UNSAFE_RouteContext,
  type LinkProps,
  type NavigateFunction,
  type NavigateOptions,
  type To,
} from 'react-router'
import { isCurrentTabClick, navigationPath } from '@/lib/navigationPreparation'
import { prepareCurveNavigation } from '@/features/history/curveTransition'

/** 默认原生页面过渡；累计收益展开或收回成功时只保留 SVG 主连续。 */
export function Link({ viewTransition = true, onClick, ...rest }: LinkProps & RefAttributes<HTMLAnchorElement>) {
  const navigate = useRouterNavigate()
  return <RouterLink viewTransition={viewTransition} {...rest} onClick={event => {
    onClick?.(event)
    if (!isCurrentTabClick(event, rest.target, rest.reloadDocument, rest.download)) return
    const url = new URL(event.currentTarget.href)
    if (url.origin !== window.location.origin || !prepareCurveNavigation(url.pathname)) return
    event.preventDefault()
    void navigate(rest.to, { replace: rest.replace ?? (url.pathname + url.search + url.hash === window.location.pathname + window.location.search + window.location.hash),
      state: rest.state, relative: rest.relative, preventScrollReset: rest.preventScrollReset,
      viewTransition: false })
  }} />
}

/** 数字导航保持历史语义；相对导航按 Router 的 route/path 规则解析准备落点。 */
// oxlint-disable-next-line react/only-export-components -- 导航原语共用准备接口
export function useNavigate(): NavigateFunction {
  const navigate = useRouterNavigate()
  const location = useLocation()
  const { matches } = useContext(UNSAFE_RouteContext)
  return useCallback<NavigateFunction>(
    (to: To | number, options?: NavigateOptions) => {
      if (typeof to === 'number') return navigate(to)
      const routeMatches = matches.filter((match, index) => index === 0 || match.route.path)
      const paths = routeMatches.map((match, index) => index === routeMatches.length - 1 ? match.pathname : match.pathnameBase)
      const animated = prepareCurveNavigation(navigationPath(to, location.pathname, paths, options?.relative))
      return navigate(to, { viewTransition: true, ...options, ...(animated ? { viewTransition: false } : {}) })
    },
    [navigate, location.pathname, matches],
  )
}
