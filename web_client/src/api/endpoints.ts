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
