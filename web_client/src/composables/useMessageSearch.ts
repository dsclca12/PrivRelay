import { onScopeDispose, ref, watch } from 'vue'
import { searchMessages } from '../api/endpoints'
import type { Message } from '../api/types'
import { useMessagesStore } from '../stores/messages'
import { ApiError } from '../api/client'

/** Server pagination, debounced filters and protection against out-of-order replies. */
export function useMessageSearch(action = '') {
  const messages = useMessagesStore()
  const keyword = ref('')
  const categoryFilter = ref('')
  const actionFilter = ref(action)
  const archivedFilter = ref(action === 'quarantine' ? 'all' : 'false')
  const page = ref(1)
  const pageSize = ref(20)
  const rows = ref<Message[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  let refreshPending = false

  async function reload(): Promise<void> {
    if (disposed) return
    clearTimeout(timer)
    timer = undefined
    refreshPending = false
    const request = ++generation
    loading.value = true
    error.value = ''
    try {
      const result = await searchMessages({
        archived: archivedFilter.value, q: keyword.value.trim(), category: categoryFilter.value, action: actionFilter.value,
        offset: (page.value - 1) * pageSize.value, limit: pageSize.value,
      })
      if (request !== generation) return
      const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value))
      if (page.value > lastPage) {
        page.value = lastPage
        return
      }
      rows.value = result.messages
      total.value = result.total
    } catch (cause) {
      if (request !== generation) return
      rows.value = []
      error.value = cause instanceof ApiError && cause.status === 400
        ? '搜索条件过长或不合法，请缩短后重试'
        : '加载消息失败，请检查连接后重试'
    } finally {
      if (request === generation) {
        loading.value = false
        if (refreshPending) schedule()
      }
    }
  }

  function schedule(delay = 0): void {
    generation++
    refreshPending = false
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      void reload()
    }, delay)
  }
  watch([keyword, categoryFilter, actionFilter, archivedFilter, pageSize], () => {
    rows.value = []
    total.value = 0
    page.value = 1
    schedule(250)
  }, { flush: 'sync' })
  watch(page, () => schedule(), { flush: 'sync' })
  // Polls and WebSocket updates can arrive faster than the search response.
  // Let the current request finish, then fetch at most one follow-up page.
  watch(() => messages.refreshVersion, () => {
    if (messages.lastSyncAt === null) return // A session reset is handled below.
    if (loading.value || timer !== undefined) refreshPending = true
    else schedule()
  })
  watch(() => messages.sessionVersion, () => {
    rows.value = []
    total.value = 0
    page.value = 1
    schedule()
  }, { flush: 'sync' })

  void reload()
  onScopeDispose(() => {
    disposed = true
    generation++
    clearTimeout(timer)
    rows.value = []
  })
  return { keyword, categoryFilter, actionFilter, archivedFilter, page, pageSize, rows, total, loading, error, reload }
}
