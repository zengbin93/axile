import { expect, test } from 'bun:test'
import { commitFonts, prepareCachedFonts } from './fonts'

test('缓存加载不发网络请求，迟到字体不自动注册，两套就绪后才统一启用', async () => {
  const originals = new Map(['caches', 'FontFace', 'document', 'fetch'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const added: unknown[] = []
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let network = 0
  class FakeFont {
    async load() { await gate; return this }
  }
  try {
    Object.defineProperties(globalThis, {
      caches: { configurable: true, value: { open: async () => ({ match: async () => new Response(new Uint8Array([1])) }) } },
      FontFace: { configurable: true, value: FakeFont },
      document: { configurable: true, value: { fonts: { add: (font: unknown) => added.push(font) } } },
      fetch: { configurable: true, value: () => { network++; throw new Error('Unexpected network') } },
    })
    const preparation = prepareCachedFonts()
    commitFonts()
    expect(added).toHaveLength(0)
    release()
    await preparation
    // 首屏决策后即使缓存就绪，也不会自行替换系统字体。
    expect(added).toHaveLength(0)
    expect(network).toBe(0)
    commitFonts()
    expect(added).toHaveLength(2)
  } finally {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})
