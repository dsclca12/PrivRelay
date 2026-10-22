import { apiFetch } from './client'
import type {
  Device,
  Health,
  Message,
  MessagesPage,
  RegisterRequest,
  RegisterResponse,
  Rules,
} from './types'

export function getHealth(): Promise<Health> {
  return apiFetch<Health>('/healthz')
}

export function listMessages(cursor: number, limit = 50): Promise<MessagesPage> {
  return apiFetch<MessagesPage>(`/api/v1/messages?cursor=${cursor}&limit=${limit}`)
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
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return apiFetch(`/api/v1/messages/search?${params}`)
}

export function restoreMessage(messageId: string, operationId: string): Promise<Message> {
  return apiFetch<Message>(`/api/v1/messages/${encodeURIComponent(messageId)}/restore`, {
    method: 'POST',
    body: { operation_id: operationId },
  })
}

export function sendFeedback(
  messageId: string,
  operationId: string,
  correctedCategory: string,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/v1/messages/${encodeURIComponent(messageId)}/feedback`, {
    method: 'POST',
    body: { operation_id: operationId, corrected_category: correctedCategory },
  })
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

export interface ServerStatus {
  messages: number
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
  return apiFetch(`/api/v1/messages/${encodeURIComponent(id)}`)
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
  return apiFetch(`/api/v1/messages/${encodeURIComponent(id)}/${archived ? 'archive' : 'unarchive'}`, { method: 'POST', body: { operation_id: operationId } })
}
export interface FeedbackExport { schema_version: number; samples: Record<string, unknown>[]; total: number; offset: number; has_more: boolean }
export function exportFeedback(purpose: 'evaluation' | 'training', includeText: boolean, offset: number): Promise<FeedbackExport> {
  return apiFetch('/api/v1/feedback/export', { method: 'POST', body: { consent: true, purpose, include_text: includeText, offset, limit: 100 } })
}
