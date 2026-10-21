// Destructive lifecycle checks are restricted to a dedicated synthetic-data project.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { generateKeyPairSync, randomUUID, sign } from 'node:crypto'

assert.equal(process.env.PRIVRELAY_COMPOSE_TEST, '1', 'Use only with an isolated test deployment')
assert.match(process.env.COMPOSE_PROJECT_NAME ?? '', /^privrelay-test-[a-z0-9-]+$/)
const compose = (...args) => execFileSync('docker', ['compose', ...args], { encoding: 'utf8', windowsHide: true, timeout: 180000 })
const base = 'http://127.0.0.1:8787'
async function request(route, { token, body, status = 200 } = {}) {
  const response = await fetch(base + route, {
    method: body === undefined ? 'GET' : 'POST', signal: AbortSignal.timeout(15000),
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  assert.equal(response.status, status, route)
  return response.json()
}
assert.equal((await request('/healthz')).classifier, 'ok')
await request('/api/v1/messages', { status: 401 })
const code = compose('logs', '--no-color', 'server').match(/One-time pairing code \(10 minutes\): (\S+)/)?.[1]
assert.ok(code, 'Initial pairing code unavailable')
const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'prime256v1' })
const device_id = randomUUID(), nonce = randomUUID()
const public_key = publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
const signature = sign('sha256', Buffer.from(`${device_id}\n${public_key}\n${nonce}\n${code}`), privateKey).toString('base64')
const { token } = await request('/api/v1/devices/register', {
  status: 201, body: { device_id, nonce, public_key, signature, pairing_code: code, name: 'Synthetic container test' },
})
const message = { message_id: randomUUID(), sender: 'TEST', body: '合成容器测试消息', received_at: Date.now(), subscription_id: 1, slot: 0 }
const upload = await request('/api/v1/messages/sync', { token, body: { messages: [message] } })
assert.equal(upload.messages[0].message_id, message.message_id)
assert.equal(upload.messages[0].classified, true)
compose('stop', 'server')
compose('run', '--rm', '--no-deps', '--entrypoint', 'sh', 'server', '-c', 'test -s /data/privrelay.enc && test -s /data/privrelay.enc.key')
compose('up', '-d', '--wait', '--wait-timeout', '120')
assert.equal((await request('/api/v1/messages/' + message.message_id, { token })).body, message.body)
const replay = await request('/api/v1/messages/sync', { token, body: { messages: [message] } })
assert.equal(replay.messages[0].message_id, message.message_id)
assert.equal((await request('/api/v1/status', { token })).messages, 1)
console.log('PASS container classifier, signed pairing, encrypted persistence, restart, authorization and replay')
