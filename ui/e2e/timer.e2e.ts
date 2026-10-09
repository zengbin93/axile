import { expect, test, type Page } from '@playwright/test'
import type { SchedulePreview } from '../src/lib/api/accounts'

type PreviewRequest = {
  after: string | null
  limit: number
  scheduled_ats?: string[]
  supplement: { count: number; interval_minutes: number } | null
}

async function mockPreview(page: Page) {
  const requests: PreviewRequest[] = []
  let failSummary = false
  let delayInterval: number | null = null
  let release: () => void = () => {}
  const times = Array.from({ length: 120 }, (_, index) => new Date(Date.UTC(2026, 9, 12 + index, 6, 55)).toISOString())
  await page.route('**/account/schedule-preview', async (route) => {
    const payload = route.request().postDataJSON() as PreviewRequest
    requests.push(payload)
    if (payload.scheduled_ats && failSummary) {
      failSummary = false
      await route.fulfill({ status: 503, json: { detail: '模拟补发预览失败' } })
      return
    }
    if (payload.scheduled_ats && payload.supplement?.interval_minutes === delayInterval) {
      await new Promise<void>((resolve) => { release = resolve })
    }
    const remaining = payload.scheduled_ats ?? times.filter((time) => !payload.after || Date.parse(time) > Date.parse(payload.after))
    const selected = payload.scheduled_ats ? remaining : remaining.slice(0, payload.limit)
    const items: SchedulePreview['items'] = selected.map((time) => {
      const closed = [0, 6].includes(new Date(time).getUTCDay())
      const count = closed || !payload.supplement ? 0 : Math.min(payload.supplement.count, Math.ceil(5 / payload.supplement.interval_minutes) - 1)
      return {
        scheduled_at: time, base_scheduled_at: payload.scheduled_ats ? time : null,
        index: 0, effective_count: count, is_last: count === 0,
        calendar_day: time.slice(0, 10), calendar_status: closed ? 'available_closed' : 'available_open',
        action: closed ? 'skip' : 'execute', reason_code: closed ? 'CALENDAR.CLOSED' : null,
        unavailable_reason: null, calendar_id: 'china', label: '中国交易日历',
      }
    })
    await route.fulfill({ json: {
      timezone: 'Asia/Shanghai', evaluated_at: '2026-10-09T15:00:00+08:00',
      calendar: { requirement: 'required', availability: 'available', unavailable_reason: null, calendar_id: 'china', label: '中国交易日历', coverage_start: '2003-01-01', coverage_end: '2026-12-31' },
      items, next_cursor: payload.scheduled_ats ? null : items.at(-1)?.scheduled_at,
      has_more: !payload.scheduled_ats && remaining.length > selected.length,
    } })
  })
  return {
    requests,
    fail: () => { failSummary = true },
    delay: (interval: number) => { delayInterval = interval },
    release: () => release(),
  }
}

test('补发编辑仅更新摘要，保留滚动位置和全部已加载时间节点', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 760 })
  await page.addInitScript(() => {
    const state = window as typeof window & { supplementAnimations: number }
    state.supplementAnimations = 0
    const original = Element.prototype.animate
    Element.prototype.animate = function (...args) {
      const root = this.getRootNode()
      const host = root instanceof ShadowRoot ? root.host : this
      if (host.closest('span[aria-label^="补 "]')) state.supplementAnimations++
      return original.apply(this, args)
    }
  })
  const mock = await mockPreview(page)
  await page.goto('/e2e/timer.html')
  const list = page.getByRole('list', { name: '未来排程预览' })
  await expect(list.locator('[aria-label="补 2 次 · 隔 1 分"]').first()).toBeVisible()
  const scroll = page.getByRole('complementary').locator('.quiet-scrollbar')
  const initialRows = await list.locator('time').count()
  await scroll.evaluate((node) => { node.scrollTop = node.scrollHeight })
  await expect.poll(() => mock.requests.filter((request) => !request.scheduled_ats).length).toBeGreaterThan(1)
  await expect.poll(() => list.locator('time').count()).toBeGreaterThan(initialRows)
  await expect.poll(async () => {
    const rows = await list.getByRole('listitem').count()
    const closed = await list.getByText('休市', { exact: true }).count()
    return await list.locator('[aria-label="补 2 次 · 隔 1 分"]').count() === rows - closed
  }).toBe(true)
  await scroll.evaluate((node) => { node.scrollTop = 100 })
  const dates = await list.locator('time').allTextContents()
  const timeNode = await list.locator('time').first().elementHandle()
  const listNode = await list.elementHandle()
  const baseRequests = mock.requests.filter((request) => !request.scheduled_ats).length
  expect(await page.evaluate(() => (window as typeof window & { supplementAnimations: number }).supplementAnimations)).toBe(0)
  await page.getByRole('button', { name: '下一档补发次数', exact: true }).click()
  await expect(list.locator('[aria-label="补 3 次 · 隔 1 分"]').first()).toBeAttached()
  await expect.poll(async () => list.locator('[aria-label="补 2 次 · 隔 1 分"]').count()).toBe(0)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { supplementAnimations: number }).supplementAnimations)).toBeGreaterThan(0)
  expect(mock.requests.filter((request) => !request.scheduled_ats)).toHaveLength(baseRequests)
  expect(await list.locator('time').allTextContents()).toEqual(dates)
  expect(await timeNode!.evaluate((node) => node.isConnected)).toBe(true)
  expect(await listNode!.evaluate((node) => node.isConnected)).toBe(true)
  expect(await scroll.evaluate((node) => node.scrollTop)).toBe(100)
  await expect(page.getByLabel('正在加载排程预览')).toHaveCount(0)
  await page.getByRole('complementary').screenshot({ path: 'test-results/timer-preview-summary.png', animations: 'disabled' })
  await page.getByRole('spinbutton', { name: '补发次数', exact: true }).focus()
  await page.keyboard.press('Home')
  await expect(list.locator('[aria-label="不补发"]').first()).toBeAttached()
  expect(await timeNode!.evaluate((node) => node.isConnected)).toBe(true)
  expect(await scroll.evaluate((node) => node.scrollTop)).toBe(100)
  await page.getByRole('complementary').screenshot({ path: 'test-results/timer-preview-disabled.png', animations: 'disabled' })
  await page.getByRole('button', { name: '下一档补发次数', exact: true }).click()
  await expect(list.locator('[aria-label="补 1 次 · 隔 1 分"]').first()).toBeAttached()
  await page.getByRole('switch', { name: '自动调仓', exact: true }).click()
  await expect(page.getByText('开启自动调仓后显示。')).toBeVisible()
  await page.getByRole('switch', { name: '自动调仓', exact: true }).click()
  await expect(list.locator('[aria-label="补 1 次 · 隔 1 分"]').first()).toBeAttached()
})

test('摘要失败可重试，快速换间隔时旧响应不能覆盖新值', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const mock = await mockPreview(page)
  await page.goto('/e2e/timer.html')
  const list = page.getByRole('list', { name: '未来排程预览' })
  await expect(list.locator('[aria-label="补 2 次 · 隔 1 分"]').first()).toBeAttached()
  const dates = await list.locator('time').allTextContents()
  const baseRequests = mock.requests.filter((request) => !request.scheduled_ats).length
  mock.fail()
  await page.getByRole('button', { name: '下一档补发间隔分钟', exact: true }).click()
  await expect(page.getByText('补发预览未更新')).toBeVisible()
  expect(await list.locator('time').allTextContents()).toEqual(dates)
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(list.locator('[aria-label="补 2 次 · 隔 2 分"]').first()).toBeAttached()
  mock.delay(3)
  await page.getByRole('button', { name: '下一档补发间隔分钟', exact: true }).click()
  await expect.poll(() => mock.requests.some((request) => request.supplement?.interval_minutes === 3)).toBe(true)
  await page.getByRole('button', { name: '下一档补发间隔分钟', exact: true }).click()
  await expect(list.locator('[aria-label="补 1 次 · 隔 4 分"]').first()).toBeAttached()
  mock.release()
  expect(await list.locator('time').allTextContents()).toEqual(dates)
  expect(mock.requests.filter((request) => !request.scheduled_ats)).toHaveLength(baseRequests)
  await expect(list.locator('[aria-label="补 1 次 · 隔 3 分"]')).toHaveCount(0)
})
