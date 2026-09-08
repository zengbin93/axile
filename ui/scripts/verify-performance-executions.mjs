import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const base = process.env.PERFORMANCE_PREVIEW_URL ?? 'http://127.0.0.1:1420'
const account = process.env.PERFORMANCE_ACCOUNT_ID ?? '2'
const output = process.env.PERFORMANCE_SCREENSHOTS ?? '/tmp/axon-clean-chart-checks'
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce', colorScheme: 'dark' })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`${base}/accounts/${account}/history`)
  const chart = page.getByTestId('performance-chart')
  await chart.waitFor()
  assert.equal(await page.getByTestId('trade-marker').count(), 0)
  assert.equal(await page.getByTestId('execution-strip').count(), 0)
  await page.screenshot({ path: `${output}/chart.png` })
  const rect = await chart.boundingBox()
  await page.mouse.move(rect.x + rect.width * 0.5, rect.y + 160)
  const card = page.getByTestId('chart-trade-card')
  await card.waitFor()
  assert.ok((await card.innerText()).includes('执行后持仓'))
  await chart.click({ position: { x: rect.width * 0.5, y: 160 } })
  assert.equal(await card.getAttribute('role'), 'dialog')
  assert.ok((await card.innerText()).includes('原持仓'))
  assert.ok((await card.innerText()).includes('BP'))
  await page.mouse.move(100, 100)
  assert.equal(await card.getAttribute('role'), 'dialog')
  const link = card.getByRole('link', { name: '执行详情', exact: true })
  const href = await link.getAttribute('href')
  await link.click()
  await page.getByRole('link', { name: '返回实盘绩效' }).click()
  await card.waitFor()
  assert.equal(await card.getByRole('link', { name: '执行详情', exact: true }).getAttribute('href'), href)
  await page.setViewportSize({ width: 390, height: 844 })
  const bounds = await card.boundingBox()
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ ok: true, screenshots: output }))
} finally { await browser.close() }
