import { useCallback } from 'react'
import {
  Link as RouterLink,
  useNavigate as useRouterNavigate,
  type LinkProps,
  type NavigateFunction,
  type NavigateOptions,
  type To,
} from 'react-router'

/**
 * 默认开启 View Transition 的路由原语（L2/L3）。
 *
 * 第一性原理：页面切换是否「丝滑」应由一处统一决定，而非在每个跳转点各自记得
 * 传 ``viewTransition``。全站从本模块引入 :func:`Link` / :func:`useNavigate`，
 * 任何跳转都自动走交叉淡入与共享元素过渡，杜绝逐处遗漏导致的「有的淡入有的硬切」。
 * 降级动画偏好由 CSS 的 ``prefers-reduced-motion`` 兜底关闭。
 */

/** 默认 ``viewTransition`` 的 Link；需要关闭时显式传 ``viewTransition={false}``。 */
export function Link({ viewTransition = true, ...rest }: LinkProps) {
  return <RouterLink viewTransition={viewTransition} {...rest} />
}

/** 默认 ``viewTransition`` 的 navigate；数字 delta（前进/后退）原样透传。 */
// oxlint-disable-next-line react/only-export-components -- 导航原语与 Link 同属一处，刻意合并
export function useNavigate(): NavigateFunction {
  const navigate = useRouterNavigate()
  return useCallback<NavigateFunction>(
    (to: To | number, options?: NavigateOptions) => {
      if (typeof to === 'number') {
        navigate(to)
        return
      }
      navigate(to, { viewTransition: true, ...options })
    },
    [navigate],
  )
}
