import {
  Bell,
  CircleCheckFilled,
  CircleCloseFilled,
  InfoFilled,
  Key,
  ShoppingCart,
  User,
  WarningFilled,
  Wallet,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'

export interface CategoryMeta {
  label: string
  icon: Component
  tagType: 'primary' | 'success' | 'info' | 'warning' | 'danger'
}

/** 六分类 + 未确定，与 PrivateSMS-Classifier 一致。 */
export const CATEGORY_META: Record<string, CategoryMeta> = {
  personal: { label: '个人短信', icon: User, tagType: 'primary' },
  otp: { label: '验证码', icon: Key, tagType: 'success' },
  service: { label: '服务通知', icon: Bell, tagType: 'info' },
  transaction: { label: '交易通知', icon: Wallet, tagType: 'primary' },
  marketing: { label: '营销短信', icon: ShoppingCart, tagType: 'warning' },
  suspicious: { label: '可疑短信', icon: WarningFilled, tagType: 'danger' },
  uncertain: { label: '未分类', icon: InfoFilled, tagType: 'info' },
}

export const CATEGORY_OPTIONS = Object.entries(CATEGORY_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

export interface ActionMeta {
  label: string
  icon: Component
  tagType: 'success' | 'danger'
}

export const ACTION_META: Record<string, ActionMeta> = {
  allow: { label: '正常', icon: CircleCheckFilled, tagType: 'success' },
  quarantine: { label: '拦截', icon: CircleCloseFilled, tagType: 'danger' },
}

export function categoryMeta(category: string): CategoryMeta {
  return CATEGORY_META[category] ?? CATEGORY_META['uncertain']!
}

export function actionMeta(action: string): ActionMeta {
  return ACTION_META[action] ?? ACTION_META['allow']!
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** epoch 毫秒 → YYYY-MM-DD HH:mm:ss */
export function formatDateTime(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) {
    return '—'
  }
  const d = new Date(ms)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** epoch 毫秒 → HH:mm:ss（用于同步时间等次要位置） */
export function formatClock(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) {
    return '—'
  }
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) {
    return '—'
  }
  return `${(value * 100).toFixed(1)}%`
}

export function shortId(id: string, keep = 12): string {
  if (id.length <= keep) {
    return id
  }
  return `${id.slice(0, keep)}…`
}

export function shortKey(key: string | undefined): string {
  if (!key) {
    return '—'
  }
  if (key.length <= 24) {
    return key
  }
  return `${key.slice(0, 24)}…`
}
