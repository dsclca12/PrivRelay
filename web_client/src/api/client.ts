/** HTTP 客户端：统一鉴权头、错误归一化、演示数据旁路。 */

const TOKEN_KEY = 'privrelay.token'
const DEVICE_KEY = 'privrelay.device_id'
const DEVICE_NAME_KEY = 'privrelay.device_name'

let memoryToken: string | null = null

const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

export function apiBase(): string {
  return BASE
}

export function getToken(): string | null {
  return memoryToken ?? localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  memoryToken = token
}

export function clearToken(): void {
  memoryToken = null
  localStorage.removeItem(TOKEN_KEY)
}

export function getDeviceId(): string {
  return localStorage.getItem(DEVICE_KEY) ?? ''
}

export function setDeviceId(deviceId: string): void {
  localStorage.setItem(DEVICE_KEY, deviceId)
}

export function getDeviceName(): string {
  return localStorage.getItem(DEVICE_NAME_KEY) ?? ''
}

export function setDeviceName(name: string): void {
  localStorage.setItem(DEVICE_NAME_KEY, name)
}

export function clearSession(): void {
  memoryToken = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(DEVICE_KEY)
  localStorage.removeItem(DEVICE_NAME_KEY)
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export interface RequestOptions {
  method?: string
  body?: unknown
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'

  if (import.meta.env.VITE_MOCK === '1') {
    const { mockRequest } = await import('./mock')
    return await mockRequest<T>(path, method, options.body)
  }

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: 'no-store',
      credentials: 'same-origin',
      signal: AbortSignal.timeout(15000),
    })
  } catch {
    throw new ApiError(0, 'network_error')
  }

  if (!response.ok) {
    let code = `http_${response.status}`
    try {
      const data = (await response.json()) as { error?: unknown }
      if (typeof data.error === 'string') {
        code = data.error
      }
    } catch {
      // 保留 http_* 错误码
    }
    throw new ApiError(response.status, code)
  }

  return (await response.json()) as T
}
