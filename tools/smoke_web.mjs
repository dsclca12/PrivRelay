// Tests the real frontend TypeScript against an isolated Go process (no model required).
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, mkdir, readFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'web_client/package.json'))
const { build } = require('esbuild')
await mkdir(path.join(root, 'artifacts'), { recursive: true })
const directory = await mkdtemp(path.join(root, 'artifacts/web-smoke-'))
const bundle = path.join(directory, 'frontend.mjs')
await build({
  stdin: { contents: `export * from './src/api/client'; export * from './src/api/endpoints'; export * from './src/utils/pairing'; export * from './src/stores/messages'; export { createPinia, setActivePinia } from 'pinia'`, resolveDir: path.join(root, 'web_client') },
  bundle: true, platform: 'node', format: 'esm', outfile: bundle,
  define: { 'import.meta.env': '{}' },
})
const reservation = createServer().listen(0, '127.0.0.1')
await once(reservation, 'listening')
const port = reservation.address().port
await new Promise(resolve => reservation.close(resolve))
const base = `http://127.0.0.1:${port}`
const executable = path.join(root, 'artifacts', process.platform === 'win32' ? 'privrelay-server.exe' : 'privrelay-server')
const server = spawn(executable, ['-listen', `127.0.0.1:${port}`, '-data', path.join(directory, 'store.enc'), '-classifier', '', '-web', path.join(root, 'web_client/dist')], { windowsHide: true })
let output = '', failure
server.stdout.on('data', chunk => { output += chunk })
server.on('error', error => { failure = error })
const storage = new Map()
globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) }
const realFetch = globalThis.fetch
let cookie = ''
globalThis.fetch = async (url, options = {}) => {
  const headers = new Headers(options.headers)
  if (cookie) headers.set('Cookie', cookie)
  if (options.method && options.method !== 'GET') headers.set('Origin', base)
  const response = await realFetch(new URL(url, base), { ...options, headers, signal: AbortSignal.timeout(10000) })
  if (response.headers.has('set-cookie')) cookie = response.headers.get('set-cookie').split(';')[0]
  return response
}
try {
  let code
  for (let i = 0; i < 100; i++) {
    if (failure) throw failure
    code = output.match(/One-time pairing code \(10 minutes\): (\S+)/)?.[1]
    if (code) break
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  assert.ok(code, 'backend startup')
  const api = await import(pathToFileURL(bundle).href)
  assert.equal((await realFetch(base)).status, 200)
  const registration = await api.buildPairingRequest({ pairingCode: code, deviceName: 'Browser integration' })
  const web = await api.registerDevice(registration)
  api.setToken(web.token)
  assert.equal(storage.has('privrelay.token'), false, 'token must stay out of localStorage')
  await api.createSession()
  api.clearToken()
  assert.equal((await api.getSession()).device_id, web.device_id)
  console.log('PASS actual WebCrypto signature, cookie session and static hosting')
  const next = await api.createPairingCode()
  const qrContract = JSON.parse(await readFile(path.join(root, 'contracts/pairing.json'), 'utf8'))
  assert.deepEqual(JSON.parse(api.buildPairingQr(qrContract.server, qrContract.pairing_code, qrContract.expires_at)), qrContract)
  for (const address of ['https://user:secret@relay.test', 'https://relay.test/api', 'https://relay.test?key=secret', 'file:///tmp']) {
    assert.throws(() => api.buildPairingQr(address, next.pairing_code, next.expires_at))
  }
  const qr = JSON.parse(api.buildPairingQr(base, next.pairing_code, next.expires_at))
  assert.equal(qr.server, base)
  assert.equal(qr.type, 'privrelay-pairing')
  assert.equal((await api.getPairingStatus()).active, true)
  const phone = await api.registerDevice(await api.buildPairingRequest({ pairingCode: next.pairing_code, deviceName: 'Synthetic Android' }))
  assert.equal((await api.getPairingStatus()).active, false)
  assert.equal((await api.getSession()).device_id, web.device_id, 'new device must not replace browser identity')
  await assert.rejects(api.registerDevice(await api.buildPairingRequest({ pairingCode: next.pairing_code, deviceName: 'Replay' })))
  console.log('PASS browser generates a single-use code for another device')
  await api.putRules({ mode: 'filter', threshold: 0.95, whitelist: ['TEST'], blacklist: [] })
  assert.deepEqual((await api.getRules()).whitelist, ['TEST'])
  const upload = await realFetch(`${base}/api/v1/messages/sync`, { method: 'POST', headers: { Authorization: `Bearer ${phone.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: [{ message_id: crypto.randomUUID(), sender: 'TEST', body: 'Synthetic frontend integration message', received_at: Date.now(), subscription_id: 1, slot: 0 }] }) })
  assert.equal(upload.status, 200)
  const page = await api.listMessages(0)
  assert.equal(page.messages.length, 1)
  assert.equal((await api.getStatus()).messages, 1)
  assert.equal(page.messages[0].device_id, phone.device_id)
  assert.equal(page.messages[0].classified, false)
  const id = page.messages[0].message_id
  const restored = await api.restoreMessage(id, crypto.randomUUID())
  assert.equal(restored.restored, true)
  api.setActivePinia(api.createPinia())
  const messages = api.useMessagesStore()
  await messages.pull()
  assert.equal(messages.summary.restored, 1)
  messages.$reset()
  assert.equal(messages.summary, null)
  assert.equal((await api.listMessages(page.cursor)).messages[0].restored, true)
  const feedbackId = crypto.randomUUID()
  assert.equal((await api.sendFeedback(id, feedbackId, 'personal')).status, 'pending_review')
  assert.equal((await api.listFeedback('pending_review')).total, 1)
  assert.equal((await api.reviewFeedback(feedbackId, 'approved')).review_status, 'approved')
  assert.equal((await api.sendFeedback(id, feedbackId, 'personal')).status, 'approved', 'a submission retry must preserve review')
  assert.equal((await api.listFeedback('approved')).counts.pending_review, 0)
  assert.equal((await api.getStatus()).pending_feedback, 0)
  assert.equal((await api.getMessage(id)).restored, true)
  await assert.rejects(api.reviewFeedback(feedbackId, 'rejected'), error => error.status === 409)
  console.log('PASS review, provenance, pending counts and retry protection')
  for (let start = 0; start < 104; start += 50) {
    const batch = Array.from({ length: Math.min(50, 104 - start) }, (_, n) => ({
      message_id: crypto.randomUUID(), sender: 'SEARCH', body: `Synthetic paging ${start + n}`,
      received_at: Date.now() + start + n, subscription_id: 1, slot: 0,
    }))
    const response = await realFetch(`${base}/api/v1/messages/sync`, { method: 'POST',
      headers: { Authorization: `Bearer ${phone.token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: batch }),
    })
    assert.equal(response.status, 200)
  }
  const search = await api.searchMessages({ q: 'Synthetic paging', device_id: phone.device_id, limit: 50 })
  const second = await api.searchMessages({ q: 'Synthetic paging', offset: 50, limit: 50 })
  const third = await api.searchMessages({ q: 'Synthetic paging', offset: 100, limit: 50 })
  assert.equal(search.total, 104)
  assert.equal(second.messages.length, 50)
  assert.equal(third.messages.length, 4)
  assert.equal(third.has_more, false)
  assert.equal(new Set([...search.messages, ...second.messages, ...third.messages].map(m => m.message_id)).size, 104)
  assert.equal((await api.searchMessages({ q: 'no-such-synthetic-message' })).total, 0)
  assert.equal((await api.getStatus()).messages, 105)
  console.log('PASS complete server search and pagination across 105 synthetic messages')
  await api.revokeDevice(phone.device_id)
  assert.equal((await api.listDevices()).find(d => d.device_id === phone.device_id).active, false)
  console.log('PASS phone upload, frontend list, rules, restore, feedback and revoke')
  await api.deleteSession()
  await assert.rejects(api.getSession(), error => error.status === 401)
  console.log('PASS logout clears the server session')
} finally {
  globalThis.fetch = realFetch
  server.kill()
  await once(server, 'exit')
}
