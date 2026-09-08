import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const base = process.env.PERFORMANCE_PREVIEW_URL ?? 'http://127.0.0.1:1437'
const account = process.env.PERFORMANCE_ACCOUNT_ID ?? '2'
const output = process.env.PERFORMANCE_SCREENSHOTS ?? '/tmp/axon-performance-20260908/screenshots'
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
const page = await context.newPage()
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (request.url().includes('/api/')) requests.push({ url: request.url(), method: request.method() }) })
const snapshotPath = `/api/v1/account/performance/${account}/snapshot`
const waitChart = () => page.locator('[data-testid=performance-chart]').waitFor()
const settle = () => page.waitForFunction(() => document.getAnimations().every(animation => animation.playState !== 'running' || animation.effect.getTiming().iterations === Infinity))
const pixels = () => page.evaluate(() => Array.from(document.querySelectorAll('[data-testid=performance-workbench] canvas')).map(canvas => {
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
  let count = 0
  for (let index = 3; index < data.length; index += 4) if (data[index]) count++
  return count
}))
const api = async path => {
  const response = await context.request.get(base + path)
  assert.equal(response.status(), 200)
  return response.json()
}

try {
  const latency = []
  for (let index = 0; index < 50; index++) {
    const start = performance.now()
    await api(snapshotPath + '?range=all')
    latency.push(performance.now() - start)
  }
  const httpP95 = latency.sort((a, b) => a - b)[47]
  assert.ok(httpP95 < 200, `HTTP P95 ${httpP95}ms`)
  await page.goto(`${base}/accounts/${account}/history`)
  await waitChart()
  assert.ok((await pixels())[0] > 1000)
  assert.equal(requests.filter(request => /\/activity|\/execute_records\//.test(request.url)).length, 0)
  assert.equal(requests.filter(request => /\/performance\/\d+\?/.test(request.url)).length, 0)
  assert.equal(requests.filter(request => request.url.includes('dimension=trade')).length, 0)
  await page.screenshot({ path: `${output}/desktop.png`, fullPage: true })
  await page.locator('[data-testid=cost-diagnostics]').scrollIntoViewIfNeeded()
  await page.locator('[data-testid=cost-diagnostics-summary]').waitFor()
  await Promise.all([page.waitForResponse(response => response.url().includes('dimension=symbol')), page.getByRole('button', { name: '按品种', exact: true }).click()])
  await settle()
  await page.waitForFunction(() => !!document.querySelector('[data-testid=cost-diagnostics-summary]'))
  await page.getByLabel('排序', { exact: true }).selectOption('cost')
  await page.getByRole('button', { name: '按执行', exact: true }).click()
  await settle()
  await page.locator('[data-testid=cost-diagnostics] button[aria-expanded]').first().click()
  await page.waitForResponse(response => response.url().includes('dimension=trade') && response.status() === 200)
  assert.ok(requests.some(request => request.url.includes('/artifacts')))
  await Promise.all([page.waitForResponse(response => response.url().includes('/snapshot?range=30')), page.getByRole('button', { name: '30 天', exact: true }).click()])
  await waitChart()
  await Promise.all([page.waitForResponse(response => response.url().includes('/snapshot?range=90')), page.getByRole('button', { name: '90 天', exact: true }).click()])
  await waitChart()
  await Promise.all([page.waitForResponse(response => response.url().includes('/snapshot?range=all')), page.getByRole('button', { name: '全部', exact: true }).click()])
  await waitChart()
  const snapshotsBeforeView = requests.filter(request => request.url.includes('/snapshot')).length
  await page.getByRole('button', { name: '每日', exact: true }).click()
  await settle()
  await page.getByRole('button', { name: '累计', exact: true }).click()
  await settle()
  assert.equal(requests.filter(request => request.url.includes('/snapshot')).length, snapshotsBeforeView)
  // Return through the SPA with the server response intentionally held back.
  await page.locator('a[href="/portfolios"]').first().click()
  await settle()
  await page.route(`**${snapshotPath}*`, async route => { await new Promise(resolve => setTimeout(resolve, 1000)); await route.continue().catch(() => {}) })
  const returnMs = await page.evaluate(async () => {
    const start = performance.now()
    history.back()
    while (!document.querySelector('[data-testid=performance-chart]')) {
      if (performance.now() - start > 2000) throw new Error('No cached chart')
      await new Promise(requestAnimationFrame)
    }
    return performance.now() - start
  })
  assert.ok(returnMs < 100, `Cached return first frame ${returnMs}ms`)
  assert.ok((await pixels())[0] > 1000)
  await page.waitForTimeout(1100)
  await page.unroute(`**${snapshotPath}*`)

  const initial = await api(snapshotPath + '?range=all')
  if (process.env.PERFORMANCE_ALLOW_SETTINGS_WRITE === '1') {
    const fee = initial.settings.backtest_fee_rate === 0.0005 ? '15' : '5'
    // Delay delivery of new results so the old effective fee can be inspected.
    let hold = true
    await page.route(`**${snapshotPath}*`, async route => {
      if (hold) await route.fulfill({ json: { ...initial, status: 'stale' } })
      else await route.continue()
    })
    await page.getByLabel('单边费率（BP）', { exact: true }).fill(fee)
    await page.getByRole('button', { name: '保存并计算', exact: true }).click()
    await page.getByText(`新费率 ${fee} BP 待计算`).waitFor()
    assert.ok(await page.getByText(`回测单边费率 ${initial.settings.backtest_fee_rate * 10000} BP`, { exact: false }).count())
    assert.ok((await pixels())[0] > 1000)
    hold = false
    await page.unroute(`**${snapshotPath}*`)
    await page.getByText(`回测单边费率 ${fee} BP`, { exact: false }).waitFor({ timeout: 15000 })
    assert.equal(await page.getByText(`新费率 ${fee} BP 待计算`).count(), 0)
  }
  const current = await api(snapshotPath + '?range=all')
  await page.route(`**${snapshotPath}*`, route => route.fulfill({ json: { ...current, status: 'failed', error: '验证用计算失败', retry_at: null } }))
  await page.getByRole('button', { name: '刷新绩效与成本', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('button[aria-label="重试：更新失败，保留上次结果"]')?.closest('[inert]') === null)
  assert.ok((await pixels())[0] > 1000)
  await page.screenshot({ path: `${output}/failed-keeps-chart.png`, fullPage: true })
  await page.unroute(`**${snapshotPath}*`)
  await page.getByRole('button', { name: '刷新绩效与成本', exact: true }).click()
  await page.waitForFunction(() => !!document.querySelector('button[aria-label="重试：更新失败，保留上次结果"]')?.closest('[inert]'))

  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
    await settle()
    await waitChart()
    assert.ok((await pixels())[0] > 1000, `Canvas at ${width}`)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Page overflow at ${width}`)
    await page.screenshot({ path: `${output}/${width}.png`, fullPage: true })
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'passed', httpP95Ms: httpP95, cachedReturnFirstFrameMs: returnMs, screenshots: output, checks: 'snapshot-only initial load, canvas pixels, ranges, daily view, lazy costs, sorting, trade/artifact expansion, shared cache, fee consistency, failed update, mobile and desktop' }, null, 2))
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true })
  console.error((await page.locator('body').innerText()).slice(0, 2500))
  throw error
} finally {
  await browser.close()
}
