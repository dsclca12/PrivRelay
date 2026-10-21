import { ref } from 'vue'
import { ApiError, apiBase, getToken } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useLogsStore } from '../stores/logs'
import { useMessagesStore } from '../stores/messages'

export type SyncStatus = 'off' | 'connecting' | 'live' | 'polling'

const POLL_INTERVAL_MS = 5000
const WS_RETRY_MS = 30000

/** 模块级单例：整个应用共享一份同步状态。 */
const status = ref<SyncStatus>('off')
const lastSyncAt = ref<number | null>(null)

let started = false
let refreshing = false
let pollTimer: ReturnType<typeof setInterval> | null = null
let wsRetryTimer: ReturnType<typeof setTimeout> | null = null
let socket: WebSocket | null = null

async function refresh(maxPages = 1): Promise<void> {
  if (refreshing) {
    return
  }
  refreshing = true
  const auth = useAuthStore()
  const messages = useMessagesStore()
  const logs = useLogsStore()
  try {
    await messages.pull(maxPages)
    lastSyncAt.value = messages.lastSyncAt
  } catch (error) {
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
  const base = apiBase()
  const origin =
    base === ''
      ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}`
      : base.replace(/^http/, 'ws')
  // 服务端当前仅从 Authorization 头读取令牌，浏览器 WebSocket 无法携带请求头，
  // 这里以 query 参数尽力传递；服务端支持后即可生效，失败则自动降级轮询。
  return `${origin}/api/v1/ws?token=${encodeURIComponent(getToken() ?? '')}`
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
  if (!getToken()) {
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
  }
  candidate.onmessage = (event) => {
    if (socket !== candidate) return
    if (typeof event.data === 'string' && event.data.includes('changed')) {
      void refresh(2)
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
    void refresh(1)
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
    pollTimer = setInterval(() => void refresh(1), POLL_INTERVAL_MS)
    // 冷启动：拉全量历史；WebSocket 不可用时轮询兜底
    void refresh(400)
  }

  function stop(): void {
    started = false
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
