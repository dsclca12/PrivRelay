import { ref } from 'vue'
import { ApiError, apiBase } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useLogsStore } from '../stores/logs'
import { useMessagesStore } from '../stores/messages'

export type SyncStatus = 'off' | 'connecting' | 'live' | 'polling'

const POLL_INTERVAL_MS = 5000
const WS_RETRY_MS = 30000

/** 模块级单例：整个应用共享一份同步状态。 */
const status = ref<SyncStatus>('off')
const lastSyncAt = ref<number | null>(null)

let generation = 0
let started = false
let refreshing = false
let pollTimer: ReturnType<typeof setInterval> | null = null
let wsRetryTimer: ReturnType<typeof setTimeout> | null = null
let socket: WebSocket | null = null

async function refresh(): Promise<void> {
  if (refreshing) {
    return
  }
  refreshing = true
  const request = generation
  const auth = useAuthStore()
  const messages = useMessagesStore()
  const logs = useLogsStore()
  try {
    await messages.pull()
    if (request !== generation) return
    lastSyncAt.value = messages.lastSyncAt
  } catch (error) {
    if (request !== generation) return
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      logs.push('error', '访问令牌失效，需要重新配对本浏览器')
      messages.$reset()
      auth.logout({ expired: true })
    } else if (error instanceof ApiError && error.code === 'network_error') {
      logs.push('warn', '网络不可用，等待下一次重试')
    } else {
      const detail = error instanceof Error ? error.message : String(error)
      logs.push('warn', `同步失败：${detail}`)
    }
  } finally {
    refreshing = false
  }
}

function buildWsUrl(): string {
  const url = new URL(`${apiBase()}/api/v1/ws`, location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function scheduleWsRetry(): void {
  if (wsRetryTimer || !started) {
    return
  }
  wsRetryTimer = setTimeout(() => {
    wsRetryTimer = null
    if (started && status.value !== 'live') {
      connectWs()
    }
  }, WS_RETRY_MS)
}

function connectWs(): void {
  if (!useAuthStore().paired || import.meta.env.VITE_MOCK === '1') {
    return
  }
  let candidate: WebSocket
  try {
    candidate = new WebSocket(buildWsUrl())
  } catch {
    status.value = 'polling'
    scheduleWsRetry()
    return
  }
  socket = candidate
  status.value = 'connecting'

  candidate.onopen = () => {
    if (socket !== candidate) return
    status.value = 'live'
    void refresh()
  }
  candidate.onmessage = (event) => {
    if (socket !== candidate) return
    if (typeof event.data === 'string' && event.data.includes('changed')) {
      void refresh()
    }
  }
  candidate.onerror = () => {
    // onclose 随后触发
  }
  candidate.onclose = () => {
    if (socket !== candidate) return
    socket = null
    status.value = 'polling'
    scheduleWsRetry()
  }
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'visible' && started) {
    void refresh()
  }
}

export function useSync() {
  function start(): void {
    if (started) {
      return
    }
    started = true
    document.addEventListener('visibilitychange', onVisibilityChange)
    connectWs()
    pollTimer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    // Only fetch aggregate metadata; each view queries its visible page.
    void refresh()
  }

  function stop(): void {
    generation++
    started = false
    lastSyncAt.value = null
    status.value = 'off'
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (wsRetryTimer) {
      clearTimeout(wsRetryTimer)
      wsRetryTimer = null
    }
    const closing = socket
    socket = null
    closing?.close()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }

  return { status, lastSyncAt, start, stop, refresh }
}
