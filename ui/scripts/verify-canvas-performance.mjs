import { execFileSync } from 'node:child_process'
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'

const base = process.env.CANVAS_PREVIEW_URL ?? 'http://127.0.0.1:1425'
const account = process.env.CANVAS_ACCOUNT_ID ?? '2'
const session = execFileSync('agent-browser', ['session', 'id', '--scope', 'worktree', '--prefix', 'canvas-check'], { encoding: 'utf8' }).trim()
const output = process.env.CANVAS_SCREENSHOTS ?? '/tmp/axon-canvas-checks'
mkdirSync(output, { recursive: true })
function browser(...args) {
  if (args[0] === 'mouse' && args[1] === 'move') { args[2] = String(Math.round(Number(args[2]))); args[3] = String(Math.round(Number(args[3]))) }
  const response = JSON.parse(execFileSync('agent-browser', ['--session', session, ...args, '--json'], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }))
  assert.equal(response.success, true, JSON.stringify(response.error))
  return response.data
}
const evaluate = code => browser('eval', code).result
const wait = code => browser('wait', '--fn', code)
const settled = () => wait('document.getAnimations().every(a => a.playState !== "running" || a.effect.getTiming().iterations === Infinity)')
const click = name => { settled(); browser('find', 'role', 'button', 'click', '--name', name, '--exact'); settled() }
const read = testid => evaluate(`document.querySelector('[data-testid="${testid}"]').innerText`)
const view = () => read('chart-viewport')
function bounds() {
  evaluate('document.querySelector("[data-testid=performance-chart]").scrollIntoView({block:"center"})')
  return evaluate('document.querySelector("[data-testid=performance-chart]").getBoundingClientRect().toJSON()')
}
function drag(from, to, y = 110) {
  const r = bounds(), width = r.width - 90
  browser('mouse', 'move', String(r.x + 12 + width * from), String(r.y + y))
  browser('mouse', 'down')
  for (let i = 1; i <= 8; i++) browser('mouse', 'move', String(r.x + 12 + width * (from + (to - from) * i / 8)), String(r.y + y))
  browser('mouse', 'up')
}
function pixels() {
  return evaluate(`Array.from(document.querySelectorAll('[data-testid=performance-workbench] canvas')).map(c => {
    const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let count = 0; for (let i = 3; i < data.length; i += 4) if (data[i]) count++;
    return { count, width: c.width, cssWidth: c.clientWidth, ratio: devicePixelRatio };
  })`)
}
function wheel(ctrlKey, deltaY = -100) {
  bounds()
  return evaluate(`(() => {
    const canvas = document.querySelector('[data-testid=performance-chart]'), r = canvas.getBoundingClientRect();
    const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: ${ctrlKey}, deltaY: ${deltaY}, clientX: r.x + r.width * 0.35, clientY: r.y + 110 });
    canvas.dispatchEvent(event); return event.defaultPrevented;
  })()`)
}
function resetView() {
  bounds(); browser('dblclick', '[data-testid=performance-chart]')
}
async function nativeWheel(rect, ctrlKey, deltaY) {
  const endpoint = browser('get', 'cdp-url')
  const url = typeof endpoint === 'string' ? endpoint : endpoint.cdpUrl
  const targets = await (await fetch(`http://${new URL(url).host}/json/list`)).json()
  const target = targets.find(target => target.type === 'page' && target.url.startsWith(base))
  assert.ok(target, 'Preview CDP page must exist')
  const socket = new WebSocket(target.webSocketDebuggerUrl)
  try {
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
    await new Promise((resolve, reject) => {
      socket.onmessage = ({ data }) => { const response = JSON.parse(data); if (response.id === 1) response.error ? reject(response.error) : resolve() }
      socket.send(JSON.stringify({ id: 1, method: 'Input.dispatchMouseEvent', params: { type: 'mouseWheel', x: rect.x + 100, y: rect.y + 110, deltaX: 0, deltaY, modifiers: ctrlKey ? 2 : 0 } }))
    })
  } finally { socket.close() }
}

try {
  browser('set', 'viewport', '1440', '1100')
  browser('open', `${base}/accounts/${account}/history`)
  const ready = '!!document.querySelector("[data-testid=cost-diagnostics]") && !!document.querySelector("[data-testid=performance-chart]")'
  try { wait(ready) } catch (error) {
    if (!evaluate('document.querySelector("main")?.textContent.includes("正在读取完整执行区间")')) throw error
    wait(ready)
  }
  const original = view()
  assert.ok(pixels()[0].count > 1000, 'Base canvas must have actual pixels')
  evaluate('document.activeElement?.blur()')
  await nativeWheel(bounds(), true, -100)
  wait(`document.querySelector('[data-testid=chart-viewport]').innerText !== ${JSON.stringify(original)}`)
  resetView()
  evaluate('document.activeElement?.blur()')
  assert.equal(wheel(true), true, 'Ctrl wheel must zoom without focus and prevent default')
  assert.notEqual(view(), original)
  browser('focus', '[data-testid=performance-chart]')
  const beforeWheel = view()
  assert.equal(wheel(false), false, 'Ordinary wheel must not be prevented when focused')
  assert.equal(view(), beforeWheel)
  const wheelBounds = bounds()
  const scrollBefore = evaluate('Array.from(document.querySelectorAll("*")).reduce((sum, e) => sum + e.scrollTop, window.scrollY)')
  browser('mouse', 'move', String(wheelBounds.x + 100), String(wheelBounds.y + 110))
  await nativeWheel(wheelBounds, false, 180)
  wait(`Array.from(document.querySelectorAll('*')).reduce((sum, e) => sum + e.scrollTop, window.scrollY) !== ${scrollBefore}`)
  assert.equal(view(), beforeWheel, 'Native ordinary wheel must scroll without zooming')
  const zoomed = view(); drag(0.5, 0.4, 476); assert.notEqual(view(), zoomed)
  resetView(); assert.equal(view(), original)
  drag(1, 0.75, 476); assert.notEqual(view(), original, 'Navigator right handle must resize the window')
  resetView()
  wheel(true)
  assert.equal(evaluate('Array.from(document.querySelectorAll("button")).some(b => ["浏览", "区间比较"].includes(b.textContent))'), false)
  const beforeSelection = view()
  drag(0.2, 0.6)
  assert.equal(view(), beforeSelection, 'Direct selection must preserve the viewport')
  wait('!!document.querySelector("button[aria-label=比较起点]")')
  const selection = evaluate('Array.from(document.querySelectorAll("button[aria-label^=比较]")).map(e => e.textContent.trim())')
  assert.ok(selection[1] > selection[0])
  const summary = read('chart-readout'), diagnostics = read('cost-diagnostics-summary')
  assert.equal(summary.match(/滑点成本 ([\d.,-]+)/)?.[1], diagnostics.match(/滑点成本 ([\d.,-]+)/)?.[1])
  assert.match(summary, /区间比较/)
  const beforeMode = selection
  const beforeModeView = view()
  click('每日')
  assert.equal(view(), beforeModeView)
  assert.deepEqual(evaluate('Array.from(document.querySelectorAll("button[aria-label^=比较]")).map(e => e.textContent.trim())'), beforeMode)
  assert.ok(pixels()[0].count > 1000)
  click('累计')
  assert.equal(view(), beforeModeView)
  const r = bounds()
  browser('mouse', 'move', String(r.x + r.width * 0.45), String(r.y + 130))
  wait('Number.parseFloat(document.querySelector("[data-testid=performance-workbench] [role=tooltip]").style.left) > 10')
  assert.ok(pixels()[1].count > 100, 'Hover and selection overlay must render')
  browser('screenshot', `${output}/desktop-comparison.png`)
  click('取消选择')
  browser('focus', '[data-testid=performance-chart]'); browser('press', 'Home'); browser('press', 'ArrowRight'); browser('press', 'Enter')
  assert.ok(evaluate('!!document.querySelector("button[aria-label=清除日期筛选]")'))
  browser('press', 'Escape'); assert.equal(evaluate('!!document.querySelector("button[aria-label=清除日期筛选]")'), false)
  browser('focus', '[data-testid=performance-chart]'); browser('press', '0')
  assert.equal(view(), original)
  browser('press', '+'); assert.notEqual(view(), original)
  browser('press', '0'); assert.equal(view(), original)
  for (const [width, height] of [[1440, 1100], [390, 844], [320, 740]]) {
    browser('set', 'viewport', String(width), String(height))
    const controls = evaluate(`Array.from(document.querySelector('[data-testid=performance-controls]').children).map(e => e.getBoundingClientRect().toJSON())`)
    if (width === 1440) assert.ok(Math.max(...controls.map(r => r.y + r.height / 2)) - Math.min(...controls.map(r => r.y + r.height / 2)) < 2, 'Desktop controls must share one row')
    else assert.ok(new Set(controls.map(r => Math.round(r.y))).size > 1, 'Mobile controls must wrap')
    assert.ok(evaluate(`Array.from(document.querySelectorAll('[data-testid=performance-controls] button, [data-testid=performance-controls] input')).filter(e => e.getBoundingClientRect().width > 0).every(e => (e.tagName === 'INPUT' ? e.parentElement : e).getBoundingClientRect().height >= 36)`))
    for (const dark of [false, true]) {
      evaluate(`document.documentElement.classList.toggle('dark', ${dark})`)
      settled(); bounds()
      assert.ok(pixels()[0].count > 1000)
      assert.equal(evaluate('document.documentElement.scrollWidth > innerWidth'), false, `Overflow at ${width}`)
      evaluate('document.querySelector("main").scrollTo(0, 0); window.scrollTo(0, 0)')
      browser('screenshot', `${output}/${width}-${dark ? 'dark' : 'light'}.png`)
    }
  }
  browser('set', 'viewport', '1440', '1100', '2')
  browser('set', 'media', 'dark', 'reduced-motion')
  settled(); bounds()
  const retina = pixels()[0]
  assert.equal(retina.width, Math.round(retina.cssWidth * 2))
  click('每日'); assert.ok(pixels()[0].count > 1000)
  browser('screenshot', `${output}/retina-daily.png`)
  // Response-only fixtures exercise unavailable/legacy data without writing to the account.
  evaluate(`(async () => {
    const realFetch = window.fetch.bind(window);
    const data = await (await realFetch('/api/v1/account/performance/${account}?range=all')).json();
    window.canvasFixture = data;
    window.fetch = async (input, init) => {
      const url = new URL(String(input), location.origin);
      if (url.pathname === '/api/v1/account/performance/${account}') return new Response(JSON.stringify(window.canvasFixture), { headers: { 'Content-Type': 'application/json' } });
      if (url.pathname === '/api/v1/account/${account}/activity') return new Response(JSON.stringify({ count: 0, data: [] }), { headers: { 'Content-Type': 'application/json' } });
      return realFetch(input, init);
    };
  })()`)
  evaluate('window.canvasFixture = { ...window.canvasFixture, points: window.canvasFixture.points.map(p => ({...p, observed_at: undefined})) }')
  click('刷新绩效与成本')
  wait('!!document.querySelector("[data-testid=performance-chart]")')
  drag(0.2, 0.6)
  assert.equal(evaluate('!!document.querySelector("button[aria-label=比较起点]")'), false, 'Legacy observations must not allow interval selection')
  assert.ok(pixels()[0].count > 1000, 'Legacy responses must remain readable')
  evaluate('window.canvasFixture = { ...window.canvasFixture, observation_count: 1, points: window.canvasFixture.points.slice(0, 1) }')
  click('刷新绩效与成本'); wait('document.querySelector("main").textContent.includes("有效观测不足两条")')
  assert.equal(evaluate('document.querySelectorAll("[data-testid=performance-workbench] canvas").length'), 0)
  evaluate(`(() => {
    const start = Date.parse('2026-01-01T09:00:00+08:00');
    const points = Array.from({length: 5000}, (_, i) => {
      const observed_at = new Date(start + i * 3600000).toISOString();
      const value = Math.sin(i / 80) * 0.06 + i * 0.00002;
      return { date: observed_at, observed_at, account_return: value, portfolio_return: i > 3200 ? null : value * 1.02, account_daily_return: Math.sin(i) * 0.001, portfolio_daily_return: i > 3200 ? null : Math.sin(i) * 0.0011, difference: null };
    });
    window.canvasFixture = {...window.canvasFixture, observation_count: 5000, points, baseline: points[0].observed_at, end: points.at(-1).observed_at, bindings: []};
  })()`)
  click('刷新绩效与成本'); wait('!!document.querySelector("[data-testid=performance-chart]")')
  click('累计'); bounds()
  assert.ok(pixels()[0].count > 1000)
  const frameTimes = evaluate(`(async () => {
    const canvas = document.querySelector('[data-testid=performance-chart]'), r = canvas.getBoundingClientRect(), times = [];
    for (let i = 0; i < 15; i++) {
      const start = performance.now();
      canvas.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: r.x + 12 + (r.width - 90) * i / 15, clientY: r.y + 110 }));
      await new Promise(requestAnimationFrame); times.push(performance.now() - start);
    }
    return times;
  })()`)
  const sorted = [...frameTimes].sort((a, b) => a - b)
  assert.ok(sorted[Math.floor(sorted.length * 0.9)] < 100, 'Dense hover must remain responsive')
  browser('screenshot', `${output}/dense-gap.png`)
  const errors = browser('errors')
  assert.ok(!errors.errors?.length, JSON.stringify(errors))
  console.log(JSON.stringify({ result: 'passed', checks: 'canvas pixels, Ctrl wheel, ordinary scrolling, double-click reset, pan, navigator, comparison, diagnostics, keyboard, responsive controls, desktop/mobile themes, retina, reduced motion, legacy, empty, dense gaps', denseHoverP90Ms: sorted[Math.floor(sorted.length * 0.9)], screenshots: output }))
} catch (error) {
  browser('screenshot', `${output}/failure.png`)
  console.error(evaluate('document.querySelector("main")?.innerText.slice(0, 1800)'))
  console.error(browser('errors'))
  throw error
} finally {
  browser('close')
}
