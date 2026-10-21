import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { listMessages } from '../api/endpoints'
import type { Message } from '../api/types'

/** 冷启动时单次最多拉取的分页数（50 条/页，400 页 ≈ 2 万条历史） */
const COLD_MAX_PAGES = 400

export const useMessagesStore = defineStore('messages', () => {
  let epoch = 0
  const byId = ref<Record<string, Message>>({})
  const cursor = ref(0)
  const hasMore = ref(false)
  const loading = ref(false)
  const loaded = ref(false)
  const lastSyncAt = ref<number | null>(null)

  /** 按接收时间倒序（同秒按服务端修订号兜底） */
  const all = computed(() =>
    Object.values(byId.value).sort(
      (a, b) => b.received_at - a.received_at || b.revision - a.revision,
    ),
  )

  const quarantined = computed(() => all.value.filter((m) => m.action === 'quarantine'))

  function apply(messages: Message[]): void {
    for (const message of messages) {
      upsert(message)
    }
  }

  function upsert(message: Message): void {
    const previous = byId.value[message.message_id]
    if (!previous || message.revision >= previous.revision) byId.value[message.message_id] = message
  }

  /**
   * 游标拉取：服务端按 revision 升序返回 > cursor 的消息。
   * 刷新时只拉一页；冷启动 / 手动刷新可传大页数。
   */
  async function pull(maxPages = 1): Promise<void> {
    if (loading.value) {
      return
    }
    loading.value = true
    const generation = epoch
    try {
      let pages = 0
      let more = true
      while (more && pages < maxPages) {
        const page = await listMessages(cursor.value, 50)
        if (generation !== epoch) return
        apply(page.messages)
        cursor.value = page.cursor
        more = page.has_more
        pages += 1
      }
      hasMore.value = more
      lastSyncAt.value = Date.now()
      loaded.value = true
    } finally {
      if (generation === epoch) loading.value = false
    }
  }

  async function coldLoad(): Promise<void> {
    if (loaded.value) {
      return
    }
    await pull(COLD_MAX_PAGES)
  }

  function $reset(): void {
    epoch++
    byId.value = {}
    cursor.value = 0
    hasMore.value = false
    loading.value = false
    loaded.value = false
    lastSyncAt.value = null
  }

  return {
    byId,
    cursor,
    hasMore,
    loading,
    loaded,
    lastSyncAt,
    all,
    quarantined,
    apply,
    upsert,
    pull,
    coldLoad,
    $reset,
  }
})
