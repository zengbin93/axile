import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'

const base = process.env.CANVAS_PREVIEW_URL ?? 'http://127.0.0.1:1425'
const account = process.env.CANVAS_ACCOUNT_ID ?? '2'
const session = execFileSync('agent-browser', ['session', 'id', '--scope', 'worktree', '--prefix', 'journal-check'], { encoding: 'utf8' }).trim()
const output = process.env.CANVAS_SCREENSHOTS ?? '/tmp/axon-canvas-checks'
mkdirSync(output, { recursive: true })
function browser(...args) {
  const result = JSON.parse(execFileSync('agent-browser', ['--session', session, ...args, '--json'], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }))
  assert.equal(result.success, true)
  return result.data
}
const evaluate = code => browser('eval', code).result
const wait = code => browser('wait', '--fn', code)
const settle = () => { evaluate('(async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame) })()'); wait('document.getAnimations().every(a => a.playState !== "running" || a.effect.getTiming().iterations === Infinity)') }
const click = selector => { settle(); browser('click', selector); settle() }
const named = (role, name) => { settle(); browser('find', 'role', role, 'click', '--name', name, '--exact'); settle() }
try {
  const snapshot = await (await fetch(`${base}/api/v1/account/performance/${account}/snapshot?range=all`)).json()
  const execution = snapshot.result.executions.findLast(row => row.transactions?.some(t => t.side === 'buy') && row.record.execution_id)
  assert.ok(execution)
  const id = execution.record.id
  const query = new URLSearchParams({ snapshot_id: snapshot.snapshot_id, performance_range: 'all', record_id: String(id) })
  const route = `${base}/accounts/${account}/executions?${query}`
  const row = `[data-journal-record="${id}"]`
  browser('set', 'viewport', '1440', '1100')
  browser('open', route)
  wait(`document.querySelector('${row} > button')?.getAttribute('aria-expanded') === 'true'`)
  wait(`!!document.querySelector('${row} [data-testid=execution-evidence]') && document.querySelectorAll('${row} [data-testid=journal-trades] tbody tr').length > 0`)
  settle()
  const tradeCount = evaluate(`document.querySelectorAll('${row} [data-testid=journal-trades] tbody tr').length`)
  assert.ok(tradeCount > 1)
  browser('screenshot', `${output}/execution-trades.png`)
  evaluate(`(() => {
    window.journalRequests = [];
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = new URL(String(input), location.origin);
      window.journalRequests.push(url.pathname + url.search);
      if (url.pathname.endsWith('/costs') && url.searchParams.get('side') === 'buy' && !window.rejectedBuy) {
        window.rejectedBuy = true;
        return new Response(JSON.stringify({detail:'temporary trade failure'}), {status:503,headers:{'Content-Type':'application/json'}});
      }
      return original(input, init);
    };
  })()`)
  click(`${row} > button`)
  click(`${row} > button`)
  wait(`document.querySelectorAll('${row} [data-testid=journal-trades] tbody tr').length === ${tradeCount}`)
  assert.equal(evaluate('window.journalRequests.filter(url => (url.includes("/events") || url.includes("/artifacts")) || url.includes("dimension=trade")).length'), 0, 'Collapse/reopen must reuse evidence and immutable trade pages')
  click(`${row} button[aria-label="成交方向"]`)
  named('option', '买入')
  wait(`document.querySelector('${row} [data-testid=journal-trades]').textContent.includes('temporary trade failure')`)
  assert.ok(evaluate(`!!document.querySelector('${row} [data-testid=execution-evidence]')`), 'Trade failure must not hide evidence')
  // ErrorNotice exposes retry only for the failed subsection.
  click(`${row} [data-testid=journal-trades] button[aria-label="重试：成交读取失败"]`)
  wait(`document.querySelectorAll('${row} [data-testid=journal-trades] tbody tr').length > 0`)
  assert.ok(evaluate(`Array.from(document.querySelectorAll('${row} [data-testid=journal-trades] tbody tr')).every(tr => tr.children[2].textContent.startsWith('买'))`))
  named('button', '按品种')
  wait('document.querySelector("[data-testid=journal-summary]")?.textContent.includes("个品种")')
  const symbol = execution.transactions.find(t => t.side === 'buy').symbol
  const symbolRow = `[data-journal-symbol="${symbol}"]`
  click(`${symbolRow} > button`)
  wait(`document.querySelectorAll('${symbolRow} [data-testid=journal-trades] tbody tr').length > 0`)
  assert.ok(evaluate(`Array.from(document.querySelectorAll('${symbolRow} [data-testid=journal-trades] tbody tr')).every(tr => tr.children[1].textContent === '${symbol}')`))
  assert.ok(evaluate(`!!document.querySelector('${symbolRow} [data-testid=journal-trades] tbody a[href*="/executions/"]')`))
  click(`${symbolRow} [data-testid=journal-trades] tbody a`)
  wait('document.querySelector("main")?.textContent.includes("返回执行记录")')
  named('link', '返回执行记录')
  wait(`document.querySelector('${symbolRow} > button')?.getAttribute('aria-expanded') === 'true'`)
  for (const width of [390, 320]) {
    browser('set', 'viewport', String(width), '844')
    settle()
    assert.equal(evaluate('document.documentElement.scrollWidth > innerWidth'), false)
    browser('screenshot', `${output}/journal-${width}.png`)
  }
  browser('open', `${base}/accounts/${account}/executions?snapshot_id=missing&performance_range=all`)
  wait('document.querySelector("main").textContent.includes("绩效快照已失效")')
  assert.equal(evaluate('!!document.querySelector("[data-testid=journal-summary]")'), false)
  browser('open', `${base}/accounts/${account}/executions?snapshot_id=s&performance_range=all&start=2&end=1`)
  wait('document.querySelector("main").textContent.includes("绩效范围链接无效")')
  assert.equal(evaluate('!!document.querySelector("[data-testid=journal-summary]")'), false)
  browser('open', `${base}/accounts/${account}/executions`)
  wait('!!document.querySelector("[data-testid=journal-summary]")')
  assert.equal(evaluate('!!document.querySelector("[data-testid=journal-source]")'), false)
  const errors = browser('errors')
  assert.equal(errors.errors.length, 0, JSON.stringify(errors))
  console.log(JSON.stringify({ result: 'passed', checks: 'single execution auto-expand, real trades, cached reopen, independent retry, buy direction, symbol grouping and identities, detail return, mobile, expired/invalid scopes, live entry', screenshots: output }))
} catch (error) {
  browser('screenshot', `${output}/journal-failure.png`)
  console.error(evaluate('document.querySelector("main")?.innerText.slice(0, 1400)'))
  throw error
} finally { browser('close') }
