// Focused state tests without a DOM or a live server.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'web_client/package.json'))
const { build } = require('esbuild')
await mkdir(path.join(root, 'artifacts'), { recursive: true })
const directory = await mkdtemp(path.join(root, 'artifacts/web-state-'))
const bundle = path.join(directory, 'tests.mjs')
await build({
  stdin: { contents: `export * from './src/composables/useMessageSearch'; export * from './src/composables/useMessageActions'; export * from './src/stores/messages'; export { effectScope, nextTick } from 'vue'; export { createPinia, setActivePinia } from 'pinia'`, resolveDir: path.join(root, 'web_client') },
  bundle: true, platform: 'node', format: 'esm', outfile: bundle, define: { 'import.meta.env': '{}' },
})
globalThis.localStorage = { getItem: () => null }
const api = await import(pathToFileURL(bundle).href)
const realFetch = globalThis.fetch
const requests = []
globalThis.fetch = (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve: data => resolve(new Response(JSON.stringify(data))), reject }))
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function until(check) {
  for (let i = 0; i < 200; i++) { if (check()) return; await delay(10) }
  assert.fail('timed out waiting for state')
}
const row = id => ({ message_id: id, body: 'synthetic', received_at: 1, revision: 1 })
const result = (ids, total = ids.length) => ({ messages: ids.map(row), total, offset: 0, has_more: false })
try {
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
  assert.equal(new URL(filtered.url, 'http://test').searchParams.get('q'), 'new filter')
  filtered.resolve(result(['fresh'], 45))
  await until(() => !search.loading.value)
  assert.equal(search.rows.value[0].message_id, 'fresh')
  search.page.value = 3
  await until(() => requests.length === 1)
  const last = requests.shift()
  assert.equal(new URL(last.url, 'http://test').searchParams.get('offset'), '40')
  last.resolve(result([], 40))
  await until(() => requests.length === 1)
  assert.equal(search.page.value, 2, 'removing the last row must clamp to the last nonempty page')
  requests.shift().resolve(result(['last-valid'], 40))
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

  const slowScope = api.effectScope()
  const slow = slowScope.run(() => api.useMessageSearch())
  const slowRequest = requests.shift()
  messages.refreshVersion++
  await api.nextTick()
  await delay(10)
  assert.equal(requests.length, 0, 'background polls must not replace a pending query')
  slowRequest.resolve(result(['slow-valid-response']))
  await until(() => !slow.loading.value)
  assert.equal(slow.rows.value[0].message_id, 'slow-valid-response', 'a response spanning a poll interval must be displayed')
  messages.refreshVersion++
  await api.nextTick()
  await until(() => requests.length === 1)
  requests.shift().resolve(result(['next-poll']))
  await until(() => !slow.loading.value)
  assert.equal(slow.rows.value[0].message_id, 'next-poll')
  slowScope.stop()
  console.log('PASS slow searches survive periodic background refresh')

  const actionScope = api.effectScope()
  const actions = actionScope.run(() => api.useMessageActions())
  const firstFeedback = actions.feedback('synthetic-message', 'service').catch(error => error)
  const duplicateFeedback = actions.feedback('synthetic-message', 'service').catch(error => error)
  assert.equal(requests.length, 1, 'concurrent clicks must share one request')
  const lostFeedback = requests.shift()
  const operationId = JSON.parse(lostFeedback.options.body).operation_id
  lostFeedback.reject(new Error('response lost after server commit'))
  await Promise.all([firstFeedback, duplicateFeedback])
  const retriedFeedback = actions.feedback('synthetic-message', 'service')
  const retryFeedbackRequest = requests.shift()
  assert.equal(JSON.parse(retryFeedbackRequest.options.body).operation_id, operationId, 'uncertain feedback retries reuse the operation key')
  retryFeedbackRequest.resolve({ status: 'pending_review' })
  await retriedFeedback
  const nextFeedback = actions.feedback('synthetic-message', 'service')
  const nextFeedbackRequest = requests.shift()
  assert.notEqual(JSON.parse(nextFeedbackRequest.options.body).operation_id, operationId, 'a new deliberate operation after success has a new key')
  nextFeedbackRequest.resolve({ status: 'pending_review' })
  await nextFeedback
  const firstRestore = actions.restore('synthetic-message').catch(error => error)
  const lostRestore = requests.shift()
  const restoreId = JSON.parse(lostRestore.options.body).operation_id
  lostRestore.reject(new Error('restore response lost'))
  await firstRestore
  const retriedRestore = actions.restore('synthetic-message')
  const restoreRequest = requests.shift()
  assert.equal(JSON.parse(restoreRequest.options.body).operation_id, restoreId)
  restoreRequest.resolve(row('synthetic-message'))
  await retriedRestore
  actionScope.stop()
  await assert.rejects(actions.restore('synthetic-message'), /disposed/)
  assert.equal(requests.length, 0)
  console.log('PASS feedback and restore concurrent clicks, uncertain retries and disposal')
} finally { globalThis.fetch = realFetch }
