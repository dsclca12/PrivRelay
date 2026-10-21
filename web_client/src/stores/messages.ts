import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getStatus } from '../api/endpoints'
import type { ServerStatus } from '../api/endpoints'

/** Only retain aggregate state. Message bodies belong to the visible search page. */
export const useMessagesStore = defineStore('messages', () => {
  let epoch = 0
  const summary = ref<ServerStatus | null>(null)
  const loading = ref(false)
  const lastSyncAt = ref<number | null>(null)
  const refreshVersion = ref(0)

  async function pull(): Promise<void> {
    if (loading.value) return
    loading.value = true
    const generation = epoch
    try {
      const result = await getStatus()
      if (generation !== epoch) return
      summary.value = result
      lastSyncAt.value = Date.now()
      refreshVersion.value++
    } finally {
      if (generation === epoch) loading.value = false
    }
  }

  function $reset(): void {
    epoch++
    summary.value = null
    loading.value = false
    lastSyncAt.value = null
    refreshVersion.value++
  }

  return { summary, loading, lastSyncAt, refreshVersion, pull, $reset }
})
