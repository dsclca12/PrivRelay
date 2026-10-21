/** 与 server/store.go 中 JSON 字段一一对应的接口契约。 */

export type MessageAction = 'allow' | 'quarantine'

export interface Message {
  message_id: string
  sender: string
  body: string
  /** epoch 毫秒 */
  received_at: number
  subscription_id: number
  slot: number
  category: string
  confidence: number
  risk: number
  needs_review: boolean
  model_version: string
  action: MessageAction | string
  reason: string
  device_id: string
  revision: number
  classified: boolean
  restored: boolean
  primary_classification?: { category: string; model_version: string; confidence: number; spam_score: number; needs_review: boolean }
  classification_source?: 'llm' | 'privatesms'
  llm_pending?: boolean
  classifier_action?: 'allow' | 'block'
  classifier_reason?: string
  classifier_threshold?: number
}

export interface Device {
  device_id: string
  name: string
  public_key?: string
  token_hash?: string
  active: boolean
  /** epoch 秒 */
  expires_at: number
}

export interface Rules {
  mode: 'classify' | 'filter' | 'block' | string
  threshold: number
  whitelist: string[]
  blacklist: string[]
}

export interface Health {
  status: string
  classifier: string
}

export interface MessagesPage {
  messages: Message[]
  cursor: number
  has_more: boolean
}

export interface RegisterRequest {
  device_id: string
  name: string
  public_key: string
  nonce: string
  pairing_code: string
  signature: string
}

export interface RegisterResponse {
  token: string
  device_id: string
}

export interface LLMSettings {
  mode: 'disabled' | 'fallback' | 'primary'
  base_url: string
  model: string
  has_api_key: boolean
  allow_http: boolean
  auto_quarantine: boolean
  threshold: number
}
