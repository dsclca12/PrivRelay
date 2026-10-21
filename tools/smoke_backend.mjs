// Real-process smoke test. Uses synthetic messages and an isolated encrypted store.
// Build artifacts/privrelay-server.exe and start the local classifier first.
import { spawn } from 'node:child_process'
import { generateKeyPairSync, randomUUID, sign } from 'node:crypto'
import { once } from 'node:events'
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const classifier = process.env.CLASSIFIER_URL || 'http://127.0.0.1:18788'
await mkdir(path.join(root, 'artifacts'), { recursive: true })
const directory = await mkdtemp(path.join(root, 'artifacts', 'backend-smoke-'))
const reservation = createServer()
reservation.listen(0, '127.0.0.1')
await once(reservation, 'listening')
const port = reservation.address().port
await new Promise(resolve => reservation.close(resolve))
const base = `http://127.0.0.1:${port}`
let child
const results = []
const timings = []
const report = { started_at: new Date().toISOString(), checks: results, requests: timings }
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

async function check(name, action) {
  const start = performance.now()
  await action()
  results.push({ name, passed: true, milliseconds: Math.round(performance.now() - start) })
  console.log(`PASS ${name}`)
}
function assert(condition, message) { if (!condition) throw new Error(message) }

async function request(method, route, { token, cookie, body, expected = 200, origin } = {}) {
  const started = performance.now()
  const response = await fetch(base + route, {
    method, signal: AbortSignal.timeout(20000),
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(cookie ? { Cookie: cookie } : {}),
      ...(origin ? { Origin: origin } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  timings.push({ method, route: route.split('?')[0], status: response.status, milliseconds: Math.round(performance.now() - started) })
  assert(response.status === expected, `${method} ${route}: expected ${expected}, received ${response.status}`)
  return { data: await response.json(), cookie: response.headers.get('set-cookie')?.split(';')[0] }
}

async function start(classifierURL = classifier) {
  child = spawn(path.join(root, 'artifacts', 'privrelay-server.exe'), ['-listen', `127.0.0.1:${port}`, '-data', path.join(directory, 'store.enc'), '-classifier', classifierURL], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let output = '', errors = ''
  child.stdout.on('data', chunk => { output += chunk })
  child.stderr.on('data', chunk => { errors += chunk })
  let startError
  child.on('error', error => { startError = error })
  for (let i = 0; i < 100; i++) {
    if (startError) throw startError
    if (child.exitCode !== null) throw new Error(`Backend startup failed: ${errors}`)
    const match = output.match(/One-time pairing code \(10 minutes\): (\S+)/)
    if (match) return match[1]
    await sleep(50)
  }
  throw new Error('Backend startup timed out')
}
async function stop() {
  if (!child || child.exitCode !== null) return
  const ended = once(child, 'exit')
  child.kill()
  await ended
}
async function pair(code, name) {
  const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' })
  const device_id = randomUUID(), nonce = randomUUID()
  const public_key = publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
  const signature = sign('sha256', Buffer.from(`${device_id}\n${public_key}\n${nonce}\n${code}`), privateKey).toString('base64')
  return (await request('POST', '/api/v1/devices/register', { expected: 201, body: { device_id, name, public_key, nonce, pairing_code: code, signature } })).data
}

try {
  for (let i = 0; ; i++) {
    try {
      const response = await fetch(classifier + '/healthz', { signal: AbortSignal.timeout(1000) })
      if (response.ok) break
    } catch {}
    if (i >= 60) throw new Error('Start the real classifier before running this smoke test')
    await sleep(1000)
  }
  const bootstrap = await start()
  let web, cookie, android
  await check('health: real ONNX classifier connected', async () => {
    const { data } = await request('GET', '/healthz')
    assert(data.classifier === 'ok', 'Classifier unavailable')
  })
  await check('unauthorized access denied', () => request('GET', '/api/v1/messages', { expected: 401 }))
  await check('signed pairing and browser session', async () => {
    web = await pair(bootstrap, 'Smoke web')
    const response = await request('POST', '/api/v1/session', { token: web.token, origin: base, body: {} })
    cookie = response.cookie
    assert(cookie, 'Session cookie missing')
    assert((await request('GET', '/api/v1/session', { cookie })).data.device_id === web.device_id, 'Cookie login failed')
  })
  await check('web-generated code pairs Android identity once', async () => {
    const { data } = await request('POST', '/api/v1/pairing-codes', { cookie, origin: base, expected: 201 })
    android = await pair(data.pairing_code, 'Smoke Android')
    // Replay uses a fresh valid signature, proving the code itself was consumed.
    try { await pair(data.pairing_code, 'Replay'); throw new Error('Replay accepted') }
    catch (error) { assert(error.message.includes('received 403'), 'Code replay did not return 403') }
  })
  const now = Date.now()
  const fixtures = [
    { message_id: randomUUID(), sender: 'PR-SMOKE', body: '【测试商店】周末全场优惠，欢迎选购，退订回T。', received_at: now, subscription_id: 101, slot: 0 },
    { message_id: randomUUID(), sender: 'PR-SMOKE', body: '【测试银行】验证码123456，请勿告知他人。', received_at: now + 1, subscription_id: 102, slot: 1 },
    { message_id: randomUUID(), sender: 'PR-NOTICE', body: '【测试快递】您的包裹已送达驿站，请及时领取。', received_at: now + 2, subscription_id: 101, slot: 0 },
  ]
  await check('real classification, quarantine and OTP protection', async () => {
    await request('PUT', '/api/v1/filter/rules', { cookie, origin: base, body: { mode: 'block', threshold: 0.95, whitelist: [], blacklist: ['PR-SMOKE'] } })
    const { data } = await request('POST', '/api/v1/messages/sync', { token: android.token, body: { messages: fixtures } })
    assert(data.messages.length === 3 && data.messages.every(m => m.classified && m.model_version), 'Missing real classification')
    assert(data.messages.every(m => m.classifier_action === 'allow' && m.classifier_reason.startsWith('review_required:') && m.classifier_threshold >= 0), 'Official scoring provenance missing')
    assert(data.messages[0].category === 'marketing' && data.messages[0].action === 'quarantine', 'Marketing not quarantined')
    assert(data.messages[1].category === 'otp' && data.messages[1].action === 'allow', 'OTP not protected')
    report.classification = data.messages.map(m => ({ category: m.category, action: m.action, model: m.model_version }))
  })
  await check('duplicate upload creates no duplicate messages', async () => {
    await request('POST', '/api/v1/messages/sync', { token: android.token, body: { messages: fixtures } })
    assert((await request('GET', '/api/v1/messages/search', { cookie })).data.total === 3, 'Duplicate persisted')
  })
  let cursor
  await check('web search, pagination and quarantine query', async () => {
    const inbox = (await request('GET', '/api/v1/messages/search?limit=1&q=PR-', { cookie })).data
    assert(inbox.total === 3 && inbox.has_more && inbox.messages[0].message_id === fixtures[2].message_id, 'Search pagination failed')
    const quarantine = (await request('GET', '/api/v1/filter/quarantine', { cookie })).data
    assert(quarantine.total === 1, 'Quarantine list incorrect')
    cursor = (await request('GET', '/api/v1/messages?cursor=0', { token: android.token })).data.cursor
  })
  await check('web restore reaches Android incremental sync', async () => {
    await request('POST', `/api/v1/messages/${fixtures[0].message_id}/restore`, { cookie, origin: base, body: { operation_id: randomUUID() } })
    const { data } = await request('GET', `/api/v1/messages?cursor=${cursor}`, { token: android.token })
    assert(data.messages.length === 1 && data.messages[0].action === 'allow' && data.messages[0].restored, 'Restore absent from phone cursor')
  })
  await check('feedback is deduplicated and preserves prediction', async () => {
    const route = `/api/v1/messages/${fixtures[0].message_id}/feedback`
    const body = { operation_id: randomUUID(), corrected_category: 'service' }
    await request('POST', route, { cookie, origin: base, body })
    await request('POST', route, { cookie, origin: base, body })
    assert((await request('GET', `/api/v1/messages/${fixtures[0].message_id}`, { cookie })).data.category === 'marketing', 'Prediction was overwritten')
    assert((await request('GET', '/api/v1/status', { cookie })).data.pending_feedback === 1, 'Feedback duplicated')
  })
  await check('cross-origin mutation is rejected', () => request('POST', '/api/v1/pairing-codes', { cookie, origin: 'https://untrusted.invalid', expected: 401 }))
  await check('server restart preserves messages, sessions and rules', async () => {
    await stop(); await start()
    assert((await request('GET', '/api/v1/messages/search', { cookie })).data.total === 3, 'Messages lost on restart')
    assert((await request('GET', '/api/v1/filter/rules', { token: android.token })).data.mode === 'block', 'Rules lost on restart')
  })
  await check('device revocation blocks phone and preserves web data', async () => {
    await request('DELETE', `/api/v1/devices/${android.device_id}`, { cookie, origin: base })
    await request('GET', '/api/v1/messages', { token: android.token, expected: 401 })
    assert((await request('GET', '/api/v1/messages/search', { cookie })).data.total === 3, 'Revocation deleted history')
  })
  await check('500 real-model messages, concurrent batches and duplicate retries conserve data', async () => {
    const batches = Array.from({ length: 10 }, (_, batch) => Array.from({ length: 50 }, (_, item) => ({
      message_id: randomUUID(), sender: 'SYNTHETIC-LOAD', body: `合成容量测试 ${batch}-${item}：周末一起吃饭。`,
      received_at: now + 1000 + batch * 50 + item, subscription_id: 1, slot: 0,
    })))
    for (let offset = 0; offset < batches.length; offset += 5) {
      await Promise.all(batches.slice(offset, offset + 5).map(async messages => {
        const uploaded = (await request('POST', '/api/v1/messages/sync', { token: web.token, body: { messages } })).data
        assert(uploaded.messages.length === 50 && uploaded.messages.every(m => m.classified && m.classifier_action === 'allow'), 'Load upload lost classification')
        await request('POST', '/api/v1/messages/sync', { token: web.token, body: { messages } })
      }))
    }
    assert((await request('GET', '/api/v1/status', { cookie })).data.messages === 503, 'Load/retry duplicated or lost messages')
    const seen = new Set()
    for (let offset = 0; offset < 500; offset += 50) {
      const page = (await request('GET', `/api/v1/messages/search?q=SYNTHETIC-LOAD&offset=${offset}&limit=50`, { cookie })).data
      assert(page.total === 500 && page.messages.length === 50, 'Load search incomplete')
      page.messages.forEach(m => seen.add(m.message_id))
    }
    assert(seen.size === 500, 'Load pagination repeated rows')
  })
  const outageFixture = { message_id: randomUUID(), sender: 'SYNTHETIC-OUTAGE', body: '合成故障恢复验证，原文必须保留。', received_at: now + 2000, subscription_id: 1, slot: 0 }
  await check('real-process classifier outage ACKs original text and retry keeps revision stable', async () => {
    await stop(); await start(classifier + '/unavailable')
    const upload = () => request('POST', '/api/v1/messages/sync', { token: web.token, body: { messages: [outageFixture] } })
    const original = (await upload()).data.messages[0]
    const retried = (await upload()).data.messages[0]
    assert(!original.classified && original.action === 'allow' && original.body === outageFixture.body, 'Outage did not fail-open durably')
    assert(retried.revision === original.revision, 'Outage replay caused a false revision')
    assert((await request('GET', '/api/v1/status', { cookie })).data.messages === 504, 'Outage lost data')
  })
  await check('model reconnect and backend restart recover pending classification without duplicates', async () => {
    await stop(); await start()
    const recovered = (await request('POST', '/api/v1/messages/sync', { token: web.token, body: { messages: [outageFixture] } })).data.messages[0]
    assert(recovered.classified && recovered.classifier_action === 'allow' && recovered.body === outageFixture.body, 'Model recovery failed')
    assert((await request('GET', '/api/v1/status', { cookie })).data.messages === 504, 'Recovery duplicated messages')
    await request('GET', '/api/v1/messages', { token: android.token, expected: 401 })
  })
  report.passed = true
  console.log(`All ${results.length} real-process checks passed.`)
} catch (error) {
  report.passed = false
  report.error = error.message
  console.error(error.message)
  process.exitCode = 1
} finally {
  await stop()
  report.finished_at = new Date().toISOString()
  await writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2))
  console.log(`Report: ${path.join(directory, 'report.json')}`)
}
