import { expect, test, type Page } from '@playwright/test'

const template = 'def notify(context):\n    pass\n'
const custom = 'def notify(context):\n    print(context)\n'
async function setup(page: Page, status: 'none' | 'default' | 'function', configured = true) {
  let account = {
    id: 1, name: '测试账户', remark: '', trade_channel: 'binance', market: '数字货币', portfolio_id: null,
    forbidden_symbols: null, risk_symbols: null, weight_precision: 0.01, execution_timeout: 60,
    long_leverage: 1, short_leverage: 1, write_empty_record: 0,
    execution_notification_status: status, execution_notification_code: status === 'none' ? null : status === 'default' ? template : custom,
    feishu_configured: configured,
  }
  const patches: Record<string, unknown>[] = []
  const trials: Record<string, unknown>[] = []
  const control = { failTemplate: false, failSave: false, templateDelay: 0, saveDelay: 0, templateReads: 0 }
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url()).pathname
    if (url.endsWith('/notification/default')) {
      control.templateReads += 1
      if (control.templateDelay) await new Promise((resolve) => setTimeout(resolve, control.templateDelay))
      await route.fulfill({ status: control.failTemplate ? 500 : 200, json: control.failTemplate ? { detail: '模板读取失败' } : { code: template } })
    } else if (url.endsWith('/notification/test') || url.endsWith('/feishu/test')) {
      trials.push(route.request().postDataJSON())
      await route.fulfill({ json: { ok: true, message: '样例函数运行成功' } })
    } else if (route.request().method() === 'PATCH') {
      const patch = route.request().postDataJSON()
      patches.push(patch)
      if (control.saveDelay) await new Promise((resolve) => setTimeout(resolve, control.saveDelay))
      if (control.failSave) return route.fulfill({ status: 500, json: { detail: '保存失败' } })
      account = { ...account, ...patch }
      account.execution_notification_status = !account.execution_notification_code ? 'none' : account.execution_notification_code.trim() === template.trim() ? 'default' : 'function'
      await route.fulfill({ json: account })
    } else if (url.endsWith('/account/1')) await route.fulfill({ json: account })
    else await route.fulfill({ json: [] })
  })
  return { patches, trials, control }
}

test('自定义重置、取消、失败重试及同一次保存保留其他草稿', async ({ page }) => {
  const { patches, control } = await setup(page, 'function', false)
  await page.goto('/e2e/notification.html')
  const webhook = page.getByPlaceholder('可粘贴整条 webhook 链接')
  await expect(page.getByRole('link', { name: '编辑与测试' })).toBeVisible()
  await expect.poll(() => webhook.evaluate((element) => element.closest('[inert]')?.getBoundingClientRect().height)).toBe(0)
  await expect(webhook.locator('xpath=ancestor::*[@inert]')).toHaveCount(1)
  await webhook.evaluate((element) => (element as HTMLInputElement).focus())
  await expect(webhook).not.toBeFocused()
  await page.locator('input').first().fill('新名称')
  control.failTemplate = true
  await page.getByRole('button', { name: '重置为默认' }).click()
  await expect(page.getByText('默认模板读取失败', { exact: true })).toBeVisible()
  await expect(page.locator('input').first()).toHaveValue('新名称')
  control.failTemplate = false
  await page.getByRole('button', { name: '重置为默认' }).click()
  await expect(webhook).toBeVisible()
  await expect(page.getByRole('link', { name: '编辑与测试' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /高级设置/ })).toBeVisible()
  await expect(page.getByText('执行通知：自定义函数 → 默认通知', { exact: false }).first()).toBeVisible()
  expect(patches).toHaveLength(0)
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.poll(() => webhook.evaluate((element) => element.closest('[inert]')?.getBoundingClientRect().height)).toBe(0)
  await expect(page.locator('input').first()).toHaveValue('测试账户')
  await page.locator('input').first().fill('新名称')
  await page.getByRole('button', { name: '重置为默认' }).click()
  control.failSave = true
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('保存失败', { exact: true }).first()).toBeVisible()
  await expect(webhook).toBeVisible()
  control.failSave = false
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => patches.length).toBe(2)
  expect(patches[1]).toEqual({ name: '新名称', execution_notification_code: template })
})

test('通知关闭但已有 Key 时重新配置显式启用，测试不保存', async ({ page }) => {
  const { patches, trials } = await setup(page, 'none')
  await page.goto('/e2e/notification.html')
  await expect(page.getByRole('link', { name: '编辑与测试' })).toHaveCount(0)
  await page.getByPlaceholder('已配置 · 留空保持不变').fill('https://open.feishu.cn/open-apis/bot/v2/hook/new-key')
  await page.getByRole('button', { name: '测试推送' }).click()
  await expect.poll(() => trials.length).toBe(1)
  expect(trials[0]).toEqual({ feishu_key: 'new-key' })
  expect(patches).toHaveLength(0)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => patches.length).toBe(1)
  expect(patches[0]).toEqual({ feishu_key: 'new-key', execution_notification_code: template })
})

test('重置后清除及撤销保留通知草稿，明确清除关闭通知', async ({ page }) => {
  const { patches } = await setup(page, 'function')
  await page.goto('/e2e/notification.html')
  await page.getByRole('button', { name: '重置为默认' }).click()
  await page.getByRole('button', { name: '清除 Webhook' }).click()
  await page.getByRole('button', { name: '撤销清除' }).click()
  await expect(page.getByText('执行通知：自定义函数 → 默认通知', { exact: false }).first()).toBeVisible()
  await page.getByRole('button', { name: '清除 Webhook' }).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => patches.length).toBe(1)
  expect(patches[0]).toEqual({ feishu_key: null, execution_notification_code: null })
})

for (const status of ['none', 'default', 'function'] as const) {
  test(`函数编辑页 ${status} 无 Webhook，试跑和保存只提交源码`, async ({ page }) => {
    const { patches, trials } = await setup(page, status)
    await page.goto('/e2e/notification.html?editor=1')
    await expect(page.getByRole('button', { name: '试跑函数' })).toBeVisible()
    await expect(page.getByRole('textbox', { name: /Webhook/ })).toHaveCount(0)
    await expect(page.getByPlaceholder(/Webhook|webhook|Key/)).toHaveCount(0)
    await page.getByRole('button', { name: '试跑函数' }).click()
    await expect.poll(() => trials.length).toBe(1)
    expect(Object.keys(trials[0])).toEqual(['code'])
    expect(patches).toHaveLength(0)
    if (status !== 'none') await page.getByRole('button', { name: '清空函数' }).click()
    await page.getByRole('button', { name: '保存', exact: true }).click()
    await expect.poll(() => patches.length).toBe(1)
    expect(patches[0]).toEqual({ execution_notification_code: status === 'none' ? template : null })
  })
}

test('读取和保存期间禁止重复操作', async ({ page }) => {
  const { patches, control } = await setup(page, 'function')
  control.templateDelay = 500
  control.saveDelay = 500
  await page.goto('/e2e/notification.html')
  await page.getByRole('button', { name: '重置为默认' }).click()
  await expect(page.getByRole('button', { name: '读取中…' })).toBeDisabled()
  await expect(page.getByRole('link', { name: /高级设置/ })).toBeVisible()
  expect(control.templateReads).toBe(1)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('button', { name: '保存中…' })).toBeDisabled()
  await expect(page.locator('input').first()).toBeDisabled()
  await expect(page.getByRole('button', { name: '保存中…' })).toHaveCount(0)
  expect(patches).toHaveLength(1)
})

test('编辑页模板失败可重试，重置只修改草稿并使试跑过期', async ({ page }) => {
  const { patches, control } = await setup(page, 'function')
  control.failTemplate = true
  await page.goto('/e2e/notification.html?editor=1')
  await expect(page.getByRole('button', { name: /重试/ })).toBeVisible()
  expect(patches).toHaveLength(0)
  control.failTemplate = false
  await page.getByRole('button', { name: /重试/ }).click()
  await page.getByRole('button', { name: '试跑函数' }).click()
  await expect(page.getByText('样例函数运行成功')).toBeVisible()
  await page.getByRole('button', { name: '重置为默认' }).click()
  await expect(page.getByText(/当前草稿未保存/)).toBeVisible()
  await expect(page.getByText("代码已改 · 结果为上次试跑").last()).toBeVisible()
  expect(patches).toHaveLength(0)
})
