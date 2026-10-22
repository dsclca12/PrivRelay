import { onScopeDispose } from 'vue'
import { restoreMessage, sendFeedback } from '../api/endpoints'
import { uuid } from '../utils/uuid'

/** Retain the idempotency key when the server may have saved a lost response. */
export function useMessageActions() {
  const operations = new Map<string, { id: string; pending?: Promise<unknown> }>()
  let disposed = false

  function run<T>(key: string, send: (id: string) => Promise<T>): Promise<T> {
    if (disposed) return Promise.reject(new Error('message view disposed'))
    let operation = operations.get(key)
    if (!operation) {
      operation = { id: uuid() }
      operations.set(key, operation)
    }
    if (operation.pending) return operation.pending as Promise<T>
    const entry = operation
    const pending = send(entry.id).then(result => {
      operations.delete(key)
      return result
    }).finally(() => { entry.pending = undefined })
    entry.pending = pending
    return pending
  }

  onScopeDispose(() => { disposed = true; operations.clear() })
  return {
    restore: (messageId: string) => run(`restore:${messageId}`, id => restoreMessage(messageId, id)),
    feedback: (messageId: string, category: string) => run(`feedback:${messageId}:${category}`, id => sendFeedback(messageId, id, category)),
  }
}
