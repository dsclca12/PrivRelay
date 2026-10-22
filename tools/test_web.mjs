// Focused state tests without a DOM or a live server.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'web_client/package.json'))
const { build } = require('esbuild')
const { parse, compileScript } = require('@vue/compiler-sfc')
await mkdir(path.join(root, 'artifacts'), { recursive: true })
const directory = await mkdtemp(path.join(root, 'artifacts/web-state-'))
const bundle = path.join(directory, 'tests.mjs')
const syncBundle = path.join(directory, 'sync-tests.mjs')
await build({
  stdin: { contents: `export * from './src/composables/useMessageSearch'; export * from './src/stores/messages'; export { setVaultCredentials, encryptVault } from './src/utils/vault'; export { effectScope, nextTick } from 'vue'; export { createPinia, setActivePinia } from 'pinia'`, resolveDir: path.join(root, 'web_client') },
  bundle: true, platform: 'node', format: 'esm', outfile: bundle, define: { 'import.meta.env': '{}' },
})
await build({
  stdin: { contents: `export * from './src/composables/useSync'; export * from './src/stores/messages'; export * from './src/stores/logs'; export { default as FeedbackView } from './src/views/FeedbackView.vue'; export { testAuth } from 'test:auth'; export { effectScope, nextTick } from 'vue'; export { createPinia, setActivePinia } from 'pinia'`, resolveDir: path.join(root, 'web_client') },
  bundle: true, platform: 'node', format: 'esm', outfile: syncBundle, define: { 'import.meta.env': '{}' },
  plugins: [{ name: 'sync-auth-fixture', setup(builder) {
    builder.onResolve({ filter: /^(test:auth|\.\.\/stores\/auth)$/ }, () => ({ path: 'auth', namespace: 'sync-fixture' }))
    builder.onLoad({ filter: /.*/, namespace: 'sync-fixture' }, () => ({ contents: `export const testAuth = { paired: true, logoutCalls: 0, logout() { this.logoutCalls++ } }; export function useAuthStore() { return testAuth }; export function errorText(code) { return code }` }))
    builder.onResolve({ filter: /^element-plus$/ }, () => ({ path: 'ui', namespace: 'ui-fixture' }))
    builder.onLoad({ filter: /.*/, namespace: 'ui-fixture' }, () => ({ contents: `export const ElMessage = { success() {}, error() {} }; export const ElMessageBox = { confirm: async () => {} }` }))
    builder.onLoad({ filter: /\.vue$/ }, async ({ path: filename }) => {
      const { descriptor } = parse(await readFile(filename, 'utf8'), { filename })
      const compiled = compileScript(descriptor, { id: filename })
      return { contents: compiled.content, loader: 'ts', resolveDir: path.dirname(filename) }
    })
  } }],
})
globalThis.localStorage = { getItem: () => null }
const api = await import(pathToFileURL(bundle).href)
const realFetch = globalThis.fetch
const requests = []
globalThis.fetch = (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve: (data, status = 200) => Promise.resolve(data).then(body => resolve(new Response(JSON.stringify(body), { status }))), reject }))
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function until(check) {
  for (let i = 0; i < 200; i++) { if (check()) return; await delay(10) }
  assert.fail('timed out waiting for state')
}
const row = (id, body = 'synthetic') => ({ message_id: id, sender: 'test', body, received_at: 1, subscription_id: -1, slot: -1, category: 'uncertain', confidence: 0, risk: 0, needs_review: true, model_version: '', action: 'allow', reason: '', device_id: 'test-device', revision: 1, classified: false, restored: false, archived: false })
const result = async (ids, total = ids.length, body = 'synthetic') => ({ messages: await Promise.all(Array.from({ length: total }, async (_, index) => { const message = row(ids[index] ?? `fixture-${index}`, body); return { ...message, ciphertext: await api.encryptVault(JSON.stringify(message)) } })), cursor: total, has_more: false })
try {
  api.setVaultCredentials('testphrase1234', { version: 1, kdf: 'PBKDF2-SHA256', iterations: 600000, salt: 'AAAAAAAAAAAAAAAAAAAAAA' })
  api.setActivePinia(api.createPinia())
  const scope = api.effectScope()
  const search = scope.run(() => api.useMessageSearch())
  const first = requests.shift()
  search.keyword.value = 'new filter'
  first.resolve(result(['stale']))
  await api.nextTick()
  assert.equal(search.rows.value.length, 0, 'typing must invalidate an in-flight response immediately')
  await until(() => requests.length === 1)
  const filtered = requests.shift()
  assert.equal(new URL(filtered.url, 'http://test').pathname, '/api/v2/encrypted-messages')
  filtered.resolve(result(['fresh'], 45, 'new filter'))
  await until(() => !search.loading.value)
  assert.equal(search.rows.value[0].message_id, 'fresh')
  search.page.value = 3
  await until(() => requests.length === 1)
  const last = requests.shift()
  assert.equal(new URL(last.url, 'http://test').searchParams.get('cursor'), '0')
  last.resolve(result([], 40, 'new filter'))
  await until(() => requests.length === 1)
  assert.equal(search.page.value, 2, 'removing the last row must clamp to the last nonempty page')
  requests.shift().resolve(result(['last-valid'], 40, 'new filter'))
  await until(() => !search.loading.value)
  search.pageSize.value = 50
  assert.equal(search.page.value, 1, 'page size changes reset pagination')
  await until(() => requests.length === 1)
  const disposed = requests.shift()
  scope.stop()
  disposed.resolve(result(['private-late-response']))
  await delay(0)
  assert.equal(search.rows.value.length, 0, 'disposed views must discard private data')
  console.log('PASS search debounce, stale responses, page clamping, size changes and disposal')

  const messages = api.useMessagesStore()
  const pending = messages.pull()
  const oldStatus = requests.shift()
  messages.$reset()
  const current = messages.pull()
  const newStatus = requests.shift()
  oldStatus.resolve({ messages: 999 })
  await pending
  assert.equal(messages.summary, null, 'logout must discard old status replies')
  assert.equal(messages.loading, true, 'old completion must not clear a new request loading state')
  newStatus.resolve({ messages: 2 })
  await current
  assert.equal(messages.summary.messages, 2)
  assert.ok(messages.lastSyncAt)
  console.log('PASS session reset and concurrent status request isolation')

  const slowScope = api.effectScope()
  const slowSearch = slowScope.run(() => api.useMessageSearch())
  const slowRequest = requests.shift()
  for (let i = 0; i < 3; i++) {
    messages.refreshVersion++
    await api.nextTick()
    await delay(0)
    assert.equal(requests.length, 0, 'polls must coalesce while a slow search is pending')
  }
  slowRequest.resolve(result(['slow-but-valid']))
  await until(() => requests.length === 1)
  assert.equal(slowSearch.rows.value[0].message_id, 'slow-but-valid', 'a search slower than polling must still publish its result')
  const followUp = requests.shift()
  followUp.resolve(result(['follow-up']))
  await until(() => !slowSearch.loading.value)
  assert.equal(slowSearch.rows.value[0].message_id, 'follow-up')
  assert.equal(requests.length, 0, 'multiple polls need only one follow-up request')

  const previousSession = slowSearch.reload()
  const privateRequest = requests.shift()
  messages.$reset()
  assert.deepEqual(slowSearch.rows.value, [], 'reset must immediately remove the previous session page')
  assert.equal(slowSearch.total.value, 0)
  privateRequest.resolve(result(['previous-session']))
  await previousSession
  assert.deepEqual(slowSearch.rows.value, [], 'an old session response must not repopulate the view')
  await until(() => requests.length === 1)
  requests.shift().resolve(result(['current-session']))
  await until(() => !slowSearch.loading.value)
  assert.equal(slowSearch.rows.value[0].message_id, 'current-session')
  slowScope.stop()
  console.log('PASS slow search poll coalescing and immediate session isolation')

  const errorScope = api.effectScope()
  const failed = errorScope.run(() => api.useMessageSearch())
  requests.shift().reject(new Error('synthetic offline'))
  await until(() => !failed.loading.value)
  assert.ok(failed.error.value)
  assert.deepEqual(failed.rows.value, [])
  const retry = failed.reload()
  requests.shift().resolve(result(['recovered']))
  await retry
  assert.equal(failed.error.value, '')
  assert.equal(failed.rows.value.length, 1)
  errorScope.stop()
  console.log('PASS network failure and explicit retry')

  const syncApi = await import(pathToFileURL(syncBundle).href)
  syncApi.setActivePinia(syncApi.createPinia())
  const syncMessages = syncApi.useMessagesStore()
  const feedbackScope = syncApi.effectScope()
  const feedback = feedbackScope.run(() => syncApi.FeedbackView.setup({}, { expose() {} }))
  const slowFeedback = requests.shift()
  syncMessages.lastSyncAt = Date.now()
  for (let i = 0; i < 3; i++) {
    syncMessages.refreshVersion++
    await syncApi.nextTick()
    assert.equal(requests.length, 0, 'background refreshes must not starve feedback requests')
  }
  const feedbackPage = total => ({ feedback: [], total, counts: {}, corrections: {} })
  slowFeedback.resolve(feedbackPage(41))
  await until(() => requests.length === 1)
  assert.equal(feedback.result.value.total, 41, 'slow feedback results must be displayed')
  requests.shift().resolve(feedbackPage(40))
  await until(() => !feedback.loading.value)
  const staleFeedback = feedback.load()
  const stalePage = requests.shift()
  feedback.filter.value = 'approved'
  const approvedPage = requests.shift()
  stalePage.resolve(feedbackPage(99))
  await staleFeedback
  assert.equal(feedback.result.value.total, 40, 'filter changes must invalidate previous feedback responses immediately')
  approvedPage.resolve(feedbackPage(2))
  await until(() => !feedback.loading.value)
  const oldDetail = feedback.open('private-message')
  const privateDetail = requests.shift()
  syncMessages.$reset()
  assert.equal(feedback.result.value, null, 'session reset must immediately clear feedback data')
  assert.equal(feedback.detail.value, null)
  privateDetail.resolve(row('previous-session-detail'))
  await oldDetail
  assert.equal(feedback.detail.value, null, 'old session details must not reopen the drawer')
  requests.shift().resolve(feedbackPage(0))
  await until(() => !feedback.loading.value)
  const createObjectURL = URL.createObjectURL
  let downloads = 0
  URL.createObjectURL = () => { downloads++; return 'blob:test' }
  try {
    feedback.exportConsent.value = true
    const exporting = feedback.downloadExport()
    const oldExport = requests.shift()
    syncMessages.$reset()
    oldExport.resolve({ samples: [row('private-export')], offset: 0, has_more: false })
    await exporting
    assert.equal(downloads, 0, 'an old session export must not create a downloadable file')
    requests.shift().resolve(feedbackPage(0))
    await until(() => !feedback.loading.value)
  } finally { URL.createObjectURL = createObjectURL }
  feedbackScope.stop()
  console.log('PASS feedback slow refresh coalescing, filter and session isolation')
  const originalGlobals = { document: globalThis.document, location: globalThis.location, WebSocket: globalThis.WebSocket }
  const sockets = []
  globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} }
  globalThis.location = { href: 'http://test/' }
  globalThis.WebSocket = class {
    constructor() { sockets.push(this) }
    close() { this.onclose?.() }
  }
  const sync = syncApi.useSync()
  let pullCalls = 0
  const pull = syncMessages.pull
  syncMessages.pull = (...args) => { pullCalls++; return pull(...args) }
  try {
    sync.start()
    const oldSync = requests.shift()
    const oldSocket = sockets.at(-1)
    sync.stop()
    syncMessages.$reset()
    sync.start()
    assert.equal(requests.length, 1, 'a new session must refresh before the old session request finishes')
    const newSync = requests.shift()
    const currentStatus = sync.status.value
    oldSocket.onopen?.()
    oldSocket.onmessage?.({ data: 'changed' })
    oldSocket.onclose?.()
    assert.equal(sync.status.value, currentStatus, 'closed session socket events must be ignored')
    oldSync.resolve({ error: 'unauthorized' }, 401)
    await delay(0)
    assert.equal(syncApi.testAuth.logoutCalls, 0, 'an old session error must not log out the new session')
    assert.equal(syncApi.useLogsStore().entries.length, 0)
    const callsBefore = pullCalls
    await sync.refresh()
    assert.equal(pullCalls, callsBefore, 'old completion must not release the current refresh lock')
    newSync.resolve({ messages: 3 })
    await until(() => !syncMessages.loading)
    assert.equal(syncMessages.summary.messages, 3)
    assert.ok(sync.lastSyncAt.value)
    sync.stop()
    const callsAfterStop = pullCalls
    await sync.refresh()
    assert.equal(pullCalls, callsAfterStop, 'stopped synchronization must not start more requests')
    assert.equal(sync.status.value, 'off')
    assert.equal(sync.lastSyncAt.value, null)
    console.log('PASS sync restart, stale authentication errors, socket events and request lock isolation')
  } finally {
    sync.stop()
    Object.assign(globalThis, originalGlobals)
  }
} finally { globalThis.fetch = realFetch }
