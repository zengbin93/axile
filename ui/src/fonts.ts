const CACHE = 'axile-fonts-v1'
const fonts = [
  ['Space Grotesk Variable', 'space-grotesk'],
  ['JetBrains Mono Variable', 'jetbrains-mono'],
] as const

const url = (name: string) =>
  `https://registry.npmmirror.com/@fontsource-variable/${name}/5.3.0/files/files/${name}-latin-wght-normal.woff2`

let ready: FontFace[] = []

// 与应用代码加载并行，只读本地缓存；不为字体延迟首屏。
export async function prepareCachedFonts() {
  try {
    const cache = await caches.open(CACHE)
    const loaded = await Promise.all(fonts.map(async ([family, name]) => {
      const response = await cache.match(url(name))
      if (!response) throw new Error('Font not cached')
      return new FontFace(family, await response.arrayBuffer(), { weight: '100 900' }).load()
    }))
    ready = loaded
  } catch {
    // 缓存不可用、缺失或字体损坏时，本次使用系统字体。
  }
}

// 仅在首次 render 前调用。迟到的字体不加入 document.fonts，避免页面中途换字。
export function commitFonts() {
  for (const font of ready) document.fonts.add(font)
}

export function warmFonts() {
  const download = async () => {
    try {
      const cache = await caches.open(CACHE)
      await Promise.all(fonts.map(async ([family, name]) => {
        const address = url(name)
        const cached = await cache.match(address)
        if (cached) {
          try {
            await new FontFace(family, await cached.arrayBuffer(), { weight: '100 900' }).load()
            return
          } catch {
            await cache.delete(address)
          }
        }
        const response = await fetch(address, { signal: AbortSignal.timeout(15000) })
        if (!response.ok) return
        // 验证后才缓存，后台字体始终不注册到当前文档。
        await new FontFace(family, await response.clone().arrayBuffer(), { weight: '100 900' }).load()
        await cache.put(address, response)
      }))
    } catch {
      // 网络或存储失败不影响页面，也不在本次会话重试。
    }
  }
  // 两帧之间让首屏先绘制，再等待空闲；不用 timeout 强行抢占繁忙首屏。
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if ('requestIdleCallback' in window) window.requestIdleCallback(() => { void download() })
    else setTimeout(() => { void download() }, 1000)
  }))
}
