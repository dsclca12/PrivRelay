import { defineStore } from 'pinia'
import { ref } from 'vue'

export type LogLevel = 'info' | 'warn' | 'error'

export interface LogEntry {
  id: number
  ts: number
  level: LogLevel
  text: string
}

const MAX_ENTRIES = 100

/** 本地运行日志：只记录事件描述，绝不写入短信正文、发送方或验证码。 */
export const useLogsStore = defineStore('logs', () => {
  const entries = ref<LogEntry[]>([])
  let seq = 0

  function push(level: LogLevel, text: string): void {
    entries.value.unshift({ id: ++seq, ts: Date.now(), level, text })
    if (entries.value.length > MAX_ENTRIES) {
      entries.value.length = MAX_ENTRIES
    }
  }

  function clear(): void {
    entries.value = []
  }

  return { entries, push, clear }
})
