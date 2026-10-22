import { ApiError, apiFetch } from './client'
import type {
  Device,
  Health,
  Message,
  MessagesPage,
  RegisterRequest,
  RegisterResponse,
  Rules,
  EncryptedMessage,
} from './types'
import { decryptVault, encryptVault, vaultGeneration } from '../utils/vault'

export function getHealth(): Promise<Health> {
  return apiFetch<Health>('/healthz')
}

export function listMessages(cursor: number, limit = 50): Promise<MessagesPage> {
  return (async () => {
    const session = vaultGeneration()
    const page = await apiFetch<Omit<MessagesPage, 'messages'> & { messages: EncryptedMessage[] }>(`/api/v2/encrypted-messages?cursor=${cursor}&limit=${limit}`)
    if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    const messages = await Promise.all(page.messages.map(async row => {
      const message = JSON.parse(await decryptVault(row.ciphertext)) as Message
      if (message.message_id !== row.message_id || message.received_at !== row.received_at) throw new Error('encrypted_message_identity_mismatch')
      return { ...message, revision: row.revision }
    }))
    if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    return { ...page, messages }
  })()
}

async function allMessages(): Promise<Message[]> {
  const all = new Map<string, Message>()
  const session = vaultGeneration()
  let cursor = 0
  for (let page = 0; page < 1000; page++) {
    const result = await listMessages(cursor, 50)
    if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    for (const message of result.messages) all.set(message.message_id, message)
    if (result.has_more && result.cursor <= cursor) throw new Error('invalid_message_cursor')
    cursor = result.cursor
    if (!result.has_more) return [...all.values()].sort((a, b) => b.received_at - a.received_at || b.message_id.localeCompare(a.message_id))
  }
  throw new Error('消息数量超过浏览器检索上限')
}

type EncryptedOperationKind = 'restore' | 'archive' | 'unarchive' | 'feedback'
async function saveEncrypted(message: Message, session: number, operationId: string, operationKind: EncryptedOperationKind): Promise<Message> {
  if (session !== vaultGeneration()) throw new Error('vault_session_changed')
  const ciphertext = await encryptVault(JSON.stringify(message))
  if (session !== vaultGeneration()) throw new Error('vault_session_changed')
  const result = await apiFetch<{ messages: (EncryptedMessage & { operation_replayed?: boolean })[] }>('/api/v2/encrypted-messages/sync', { method: 'POST', body: { messages: [{ message_id: message.message_id, received_at: message.received_at, ciphertext, base_revision: message.revision, operation_id: operationId, operation_kind: operationKind }] } })
  if (session !== vaultGeneration()) throw new Error('vault_session_changed')
  const saved = result.messages.find(row => row.message_id === message.message_id)
  if (!saved || saved.received_at !== message.received_at || !Number.isSafeInteger(saved.revision) || saved.revision <= 0) throw new Error('invalid_message_ack')
  if (saved.operation_replayed === true) {
    const current = JSON.parse(await decryptVault(saved.ciphertext)) as Message
    if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    if (current.message_id !== saved.message_id || current.received_at !== saved.received_at) throw new Error('invalid_message_ack')
    return { ...current, revision: saved.revision }
  }
  if (saved.ciphertext !== ciphertext) throw new Error('invalid_message_ack')
  return { ...message, revision: saved.revision }
}

export interface MessageSearch {
  archived?: string
  q?: string
  category?: string
  action?: string
  device_id?: string
  offset?: number
  limit?: number
}
export interface SearchPage {
  messages: Message[]
  total: number
  offset: number
  has_more: boolean
}
export function searchMessages(query: MessageSearch): Promise<SearchPage> {
  return (async () => {
    const filtered = (await allMessages()).filter(m => {
      const q = query.q?.toLocaleLowerCase()
      return (!q || `${m.sender}\n${m.body}`.toLocaleLowerCase().includes(q)) && (!query.category || m.category === query.category) && (!query.action || m.action === query.action) && (!query.device_id || m.device_id === query.device_id) && (query.archived === 'all' || m.archived === (query.archived === 'true'))
    })
    const offset = query.offset ?? 0, limit = query.limit ?? 50
    return { messages: filtered.slice(offset, offset + limit), total: filtered.length, offset, has_more: offset + limit < filtered.length }
  })()
}

export function restoreMessage(messageId: string, operationId: string): Promise<Message> {
  return updateEncrypted(messageId, m => ({ ...m, action: 'allow', restored: true, archived: false, reason: '用户恢复' }), operationId, 'restore')
}

export function sendFeedback(
  messageId: string,
  operationId: string,
  correctedCategory: string,
): Promise<{ status: string }> {
  return updateEncrypted(messageId, message => ({ ...message, corrected_category: correctedCategory }), operationId, 'feedback').then(() => ({ status: 'stored_encrypted' }))
}

export function getRules(): Promise<Rules> {
  return apiFetch<Rules>('/api/v1/filter/rules')
}

export function putRules(rules: Rules): Promise<Rules> {
  return apiFetch<Rules>('/api/v1/filter/rules', { method: 'PUT', body: rules })
}

export function listDevices(): Promise<Device[]> {
  return apiFetch<Device[]>('/api/v1/devices')
}

export function revokeDevice(deviceId: string): Promise<{ revoked: boolean }> {
  return apiFetch<{ revoked: boolean }>(`/api/v1/devices/${encodeURIComponent(deviceId)}`, {
    method: 'DELETE',
  })
}

export function registerDevice(request: RegisterRequest): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>('/api/v1/devices/register', {
    method: 'POST',
    body: request,
  })
}

export interface BrowserSession { device_id: string; name: string }
export function getSession(): Promise<BrowserSession> {
  return apiFetch<BrowserSession>('/api/v1/session')
}
export function createSession(): Promise<string> {
  return apiFetch<string>('/api/v1/session', { method: 'POST' })
}
export function deleteSession(): Promise<{ logged_out: boolean }> {
  return apiFetch('/api/v1/session', { method: 'DELETE' })
}
export function createPairingCode(): Promise<{ pairing_code: string; expires_at: number }> {
  return apiFetch('/api/v1/pairing-codes', { method: 'POST' })
}
export function getPairingStatus(): Promise<{ active: boolean; expires_at: number }> {
  return apiFetch('/api/v1/pairing-codes')
}
export function getVaultParams(): Promise<{ version: number; kdf: string; iterations: number; salt: string }> {
  return apiFetch('/api/v2/crypto/params')
}
export function purgeLegacyPlaintext(): Promise<{ deleted: number }> {
  return apiFetch('/api/v2/legacy-migration', { method: 'POST', body: { complete: true } })
}

export interface ServerStatus {
  messages: number
  encrypted_messages?: number
  e2ee_enabled?: boolean
  quarantined: number
  restored: number
  quarantine_reasons: Record<string, number>
  pending_classification: number
  authorized_devices: number
  connected_devices: number
  pending_feedback: number
  revision: number
}
export function getStatus(): Promise<ServerStatus> {
  return apiFetch('/api/v1/status')
}

export type ReviewStatus = 'pending_review' | 'approved' | 'rejected'
export interface Feedback {
  operation_id: string
  message_id: string
  corrected_category: string
  predicted_category?: string
  model_version?: string
  review_status: ReviewStatus
  reviewed_by?: string
  reviewed_at?: number
}
export interface FeedbackPage {
  feedback: Feedback[]
  total: number
  counts: Record<ReviewStatus, number>
  corrections: Record<string, number>
}
export function listFeedback(status = '', offset = 0, limit = 20): Promise<FeedbackPage> {
  return apiFetch(`/api/v1/feedback?${new URLSearchParams({ status, offset: String(offset), limit: String(limit) })}`)
}
export function reviewFeedback(id: string, status: 'approved' | 'rejected'): Promise<Feedback> {
  return apiFetch(`/api/v1/feedback/${encodeURIComponent(id)}`, {
    method: 'PUT', body: { review_status: status },
  })
}
export function getMessage(id: string): Promise<Message> {
  return allMessages().then(messages => {
    const message = messages.find(item => item.message_id === id)
    if (!message) throw new Error('message_not_found')
    return message
  })
}

async function updateEncrypted(id: string, update: (message: Message) => Message, operationId: string, operationKind: EncryptedOperationKind): Promise<Message> {
  const session = vaultGeneration()
  for (let attempt = 0; attempt < 3; attempt++) {
    const original = await getMessage(id)
    if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    const message = update(original)
    try { return await saveEncrypted(message, session, operationId, operationKind) }
    catch (error) {
      if (!(error instanceof ApiError && error.status === 409 && error.code === 'revision_conflict') || attempt === 2) throw error
    }
  }
  throw new Error('revision_conflict')
}

export function getLLMSettings(): Promise<import('./types').LLMSettings> {
  return apiFetch('/api/v1/ai/settings')
}
export function putLLMSettings(settings: import('./types').LLMSettings & { api_key?: string; clear_api_key?: boolean }): Promise<import('./types').LLMSettings> {
  return apiFetch('/api/v1/ai/settings', { method: 'PUT', body: settings })
}
export function testLLM(): Promise<{ category: string; model_version: string; synthetic: boolean }> {
  return apiFetch('/api/v1/ai/test', { method: 'POST', body: {} })
}

export function archiveMessage(id: string, archived: boolean, operationId: string): Promise<Message> {
  return updateEncrypted(id, message => ({ ...message, archived }), operationId, archived ? 'archive' : 'unarchive')
}
export interface FeedbackExport { schema_version: number; samples: Record<string, unknown>[]; total: number; offset: number; has_more: boolean }
export function exportFeedback(purpose: 'evaluation' | 'training', includeText: boolean, offset: number): Promise<FeedbackExport> {
  return apiFetch('/api/v1/feedback/export', { method: 'POST', body: { consent: true, purpose, include_text: includeText, offset, limit: 100 } })
}
