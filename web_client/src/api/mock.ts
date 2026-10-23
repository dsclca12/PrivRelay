/**
 * 演示数据层（VITE_MOCK=1）。
 * 让前端在没有 Go 服务与分类服务的情况下可以完整走通所有页面。
 */
import type { Device, Message, Rules } from './types'
import type { Feedback } from './endpoints'

let demoAI = { mode: 'disabled', base_url: '', model: '', has_api_key: false, allow_http: false, auto_quarantine: false, threshold: 0.95 }
interface MockState {
  feedback: Feedback[]
  messages: Message[]
  devices: Device[]
  rules: Rules
  revision: number
}

function daysAgo(days: number, hour: number, minute: number): number {
  const d = new Date()
  d.setDate(d.getDate() - days)
  d.setHours(hour, minute, 0, 0)
  return d.getTime()
}

function makeMessage(partial: Partial<Message> & Pick<Message, 'message_id' | 'sender' | 'body' | 'received_at' | 'revision'>): Message {
  return {
    subscription_id: 1,
    slot: 1,
    category: 'personal',
    confidence: 0.97,
    risk: 0.03,
    needs_review: false,
    model_version: 'rbt3-six-class@2026.08',
    action: 'allow',
    reason: '仅分类，正常保留',
    device_id: 'demo-pixel8-7f21c4a9',
    classified: true,
    restored: false,
    ...partial,
  }
}

function initialState(): MockState {
  const messages: Message[] = [
    makeMessage({
      message_id: '01995a11-0001-7000-8000-000000000001',
      sender: '10086',
      body: '【中国移动】您本月流量已使用 82%，剩余 3.6GB，可发送 CXLL 至 10086 查询。',
      received_at: daysAgo(0, 9, 12),
      category: 'service',
      confidence: 0.93,
      risk: 0.12,
      revision: 1,
      reason: '仅分类，正常保留',
    }),
    makeMessage({
      message_id: '01995a11-0002-7000-8000-000000000002',
      sender: '95588',
      body: '【工商银行】您的尾号 6612 账户 10 月 21 日 09:30 支出人民币 128.00 元，余额 4,203.55 元。',
      received_at: daysAgo(0, 9, 30),
      category: 'transaction',
      confidence: 0.98,
      risk: 0.02,
      revision: 2,
      reason: '重要短信保护',
    }),
    makeMessage({
      message_id: '01995a11-0003-7000-8000-000000000003',
      sender: '1069001234567',
      body: '【某电商】双11预售狂欢！全场五折起，点击链接 t.cn/A1xxy 领取 300 元大额券，退订回T。',
      received_at: daysAgo(0, 10, 5),
      category: 'marketing',
      confidence: 0.97,
      risk: 0.91,
      action: 'quarantine',
      reason: '已校准模型达到用户阈值',
      revision: 3,
    }),
    makeMessage({
      message_id: '01995a11-0004-7000-8000-000000000004',
      sender: '10010',
      body: '您的登录验证码为 483921，5 分钟内有效，请勿泄露给他人。',
      received_at: daysAgo(0, 10, 42),
      category: 'otp',
      confidence: 0.99,
      risk: 0.01,
      slot: 2,
      subscription_id: 2,
      reason: '重要短信保护',
      revision: 4,
    }),
    makeMessage({
      message_id: '01995a11-0005-7000-8000-000000000005',
      sender: '10698009555',
      body: '【贷款通知】恭喜您获得 80,000 元预批额度，年化 3.6%，回复「领取」立即到账。',
      received_at: daysAgo(0, 11, 2),
      category: 'suspicious',
      confidence: 0.9,
      risk: 0.88,
      action: 'quarantine',
      reason: '已校准模型达到用户阈值',
      revision: 5,
    }),
    makeMessage({
      message_id: '01995a11-0006-7000-8000-000000000006',
      sender: '姐姐',
      body: '晚上回来吃饭吗？妈说炖了你爱喝的汤。',
      received_at: daysAgo(0, 12, 20),
      category: 'personal',
      confidence: 0.96,
      risk: 0.02,
      revision: 6,
    }),
    makeMessage({
      message_id: '01995a11-0007-7000-8000-000000000007',
      sender: '95533',
      body: '【建设银行】您尾号 3308 的信用卡本期账单 1,860.40 元，最后还款日 10 月 28 日。',
      received_at: daysAgo(1, 8, 50),
      category: 'transaction',
      confidence: 0.97,
      risk: 0.04,
      revision: 7,
    }),
    makeMessage({
      message_id: '01995a11-0008-7000-8000-000000000008',
      sender: '10690333888',
      body: '【积分商城】您有 12,800 积分即将过期，速来兑换空气炸锅 → j.cn/bY2k',
      received_at: daysAgo(1, 14, 18),
      category: 'marketing',
      confidence: 0.95,
      risk: 0.86,
      action: 'quarantine',
      reason: '已校准模型达到用户阈值',
      revision: 8,
    }),
    makeMessage({
      message_id: '01995a11-0009-7000-8000-000000000009',
      sender: '95555',
      body: '【招商银行】验证码 726451，您正在办理账户变更，切勿转发。',
      received_at: daysAgo(1, 16, 40),
      category: 'otp',
      confidence: 0.99,
      risk: 0.01,
      revision: 9,
      reason: '重要短信保护',
    }),
    makeMessage({
      message_id: '01995a11-0010-7000-8000-000000000010',
      sender: '10657050',
      body: '【快递】您的包裹已到丰巢柜 A-18，请凭取件码 8814 于 24 小时内领取。',
      received_at: daysAgo(2, 10, 5),
      category: 'service',
      confidence: 0.91,
      risk: 0.08,
      revision: 10,
    }),
    makeMessage({
      message_id: '01995a11-0011-7000-8000-000000000011',
      sender: '10000',
      body: '【电信】尊敬的用户，您的套餐已于今日升级为 5G 畅享 199 元档，下月生效。',
      received_at: daysAgo(2, 11, 30),
      category: 'service',
      confidence: 0.89,
      risk: 0.1,
      revision: 11,
    }),
    makeMessage({
      message_id: '01995a11-0012-7000-8000-000000000012',
      sender: '10690005555',
      body: '【中奖通知】您已被后台抽中为幸运用户，添加客服 QQ 领取 MacBook Pro，逾期作废。',
      received_at: daysAgo(3, 20, 15),
      category: 'suspicious',
      confidence: 0.86,
      risk: 0.93,
      action: 'quarantine',
      reason: '已校准模型达到用户阈值',
      revision: 12,
    }),
    makeMessage({
      message_id: '01995a11-0013-7000-8000-000000000013',
      sender: '95599',
      body: '【农业银行】您尾号 0921 账户发生动账交易，详情请登录手机银行核实。',
      received_at: daysAgo(3, 21, 2),
      category: 'uncertain',
      confidence: 0,
      risk: 0,
      needs_review: true,
      classified: false,
      model_version: '',
      action: 'allow',
      reason: '分类不可用，正常保留',
      revision: 13,
    }),
    makeMessage({
      message_id: '01995a11-0014-7000-8000-000000000014',
      sender: '老王',
      body: '明天上午的会改到 10 点了，材料我放共享盘了。',
      received_at: daysAgo(4, 8, 5),
      category: 'personal',
      confidence: 0.95,
      risk: 0.02,
      revision: 14,
      action: 'allow',
      reason: '用户恢复',
      restored: true,
    }),
  ]

  const devices: Device[] = [
    {
      device_id: 'demo-pixel8-7f21c4a9',
      name: 'Pixel 8 · 手机',
      public_key: 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEf2k8m1nQzCnJ8vXr5wP4tLdRyHs0aGbVcNuOeXmI1qZtKpQrWsYvBnAcD0fGhJlMnOpQrStUvWxYzA==',
      active: true,
      expires_at: Math.floor(Date.now() / 1000) + 82 * 24 * 3600,
    },
    {
      device_id: 'demo-workstation-31b0',
      name: '工作站 · Windows',
      public_key: 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEh3jKw9LpQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOpQ==',
      active: false,
      expires_at: Math.floor(Date.now() / 1000) - 3 * 24 * 3600,
    },
  ]

  const rules: Rules = {
    mode: 'filter',
    threshold: 0.95,
    whitelist: ['10086', '95588'],
    blacklist: ['10690005555'],
  }

  return { feedback: [], messages, devices, rules, revision: 14 }
}

let state: MockState | null = null

function ensureState(): MockState {
  if (!state) {
    state = initialState()
  }
  return state
}

function delay(ms = 160): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function notFound(): never {
  throw new Error('mock_not_found')
}

/** 模拟 HTTP 传输：每次响应都返回新的 JSON 副本，避免与内存数据共享引用导致响应式更新缺失。 */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export async function mockRequest<T>(path: string, method: string, body: unknown): Promise<T> {
  await delay()
  const s = ensureState()
  const url = new URL(path, 'http://mock.local')

  if (url.pathname === '/api/v1/ai/settings') {
    if (method === 'PUT') {
      const input = body as typeof demoAI & { api_key?: string; clear_api_key?: boolean }
      demoAI = { mode: input.mode, base_url: input.base_url, model: input.model,
        has_api_key: input.clear_api_key ? false : Boolean(input.api_key) || (input.base_url === demoAI.base_url && demoAI.has_api_key),
        allow_http: input.allow_http, auto_quarantine: input.auto_quarantine, threshold: input.threshold }
    }
    return clone(demoAI) as T
  }
  if (url.pathname === '/api/v1/ai/test') {
    return { category: 'marketing', model_version: 'demo-only', synthetic: true } as T
  }
  if (url.pathname === '/api/v1/session') {
    if (method === 'POST') {
      localStorage.setItem('privrelay.demo-session', '1')
      return 'demo-pixel8-7f21c4a9' as T
    }
    if (method === 'DELETE') {
      localStorage.removeItem('privrelay.demo-session')
      return { logged_out: true } as T
    }
    if (!localStorage.getItem('privrelay.demo-session')) throw new Error('pairing_required')
    return { device_id: 'demo-pixel8-7f21c4a9', name: '演示浏览器', role: 'admin' } as T
  }
  if (url.pathname === '/api/v1/pairing-codes' && method === 'POST') {
    localStorage.setItem('privrelay.demo-pairing-role', String((body as { role?: string } | undefined)?.role ?? 'editor'))
    const expires = Math.floor(Date.now() / 1000) + 600
    localStorage.setItem('privrelay.demo-pairing-expires', String(expires))
    return { pairing_code: 'demo-pairing-code', expires_at: expires } as T
  }
  if (url.pathname === '/api/v1/pairing-codes' && method === 'GET') {
    const expires = Number(localStorage.getItem('privrelay.demo-pairing-expires') ?? 0)
    return { active: expires * 1000 > Date.now(), expires_at: expires } as T
  }
  if (url.pathname === '/api/v1/status') {
    return { messages: s.messages.length, quarantined: s.messages.filter(m => m.action === 'quarantine').length, restored: s.messages.filter(m => m.restored).length, quarantine_reasons: Object.fromEntries([...new Set(s.messages.filter(m => m.action === 'quarantine').map(m => m.reason))].map(reason => [reason, s.messages.filter(m => m.action === 'quarantine' && m.reason === reason).length])), pending_classification: s.messages.filter(m => !m.classified).length, authorized_devices: s.devices.filter(d => d.active).length, connected_devices: 0, pending_feedback: s.feedback.filter(f => f.review_status === 'pending_review').length, revision: s.revision } as T
  }
  if (url.pathname === '/healthz') {
    return { status: 'ok', classifier: 'ok' } as T
  }

  if (url.pathname === '/api/v1/messages/search' && method === 'GET') {
    const archived = url.searchParams.get('archived') || 'false'
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const category = url.searchParams.get('category')
    const action = url.searchParams.get('action')
    const device = url.searchParams.get('device_id')
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const rows = s.messages.filter(m => (archived === 'all' || !!m.archived === (archived === 'true')) && (!category || m.category === category) && (!action || m.action === action) &&
      (!device || m.device_id === device) && (!q || m.sender.toLowerCase().includes(q) || m.body.toLowerCase().includes(q)))
      .sort((a, b) => b.received_at - a.received_at || a.message_id.localeCompare(b.message_id))
    return clone({ messages: rows.slice(offset, offset + limit), total: rows.length, offset, has_more: offset + limit < rows.length }) as T
  }
  if (url.pathname === '/api/v1/feedback/export' && method === 'POST') {
    const input = body as { consent: boolean; purpose: string; include_text: boolean; offset: number; limit: number }
    if (!input.consent || !['evaluation', 'training'].includes(input.purpose)) throw new Error('export_consent_required')
    const rows = s.feedback.filter(f => f.review_status === 'approved' && !f.withdrawn_at).sort((a, b) => a.operation_id.localeCompare(b.operation_id))
    const samples = rows.slice(input.offset, input.offset + input.limit).map(f => {
      const message = s.messages.find(m => m.message_id === f.message_id)
      return { operation_id: f.operation_id, message_id: f.message_id, label: f.corrected_category,
        predicted_category: f.predicted_category, model_version: f.model_version, reviewed_at: f.reviewed_at,
        ...(input.include_text && message ? { text: message.body, sender: message.sender } : {}) }
    })
    return clone({ schema_version: 1, export_id: `demo-export-${Date.now()}`, consent: true, samples, total: rows.length, offset: input.offset, has_more: input.offset + input.limit < rows.length, purpose: input.purpose, include_text: input.include_text }) as T
  }
  if (url.pathname === '/api/v1/feedback' && method === 'GET') {
    const status = url.searchParams.get('status')
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const rows = s.feedback.filter(f => !status || (f.withdrawn_at ? 'withdrawn' : f.review_status) === status).sort((a, b) => a.operation_id.localeCompare(b.operation_id))
    const counts = { pending_review: 0, approved: 0, rejected: 0, withdrawn: 0 }
    const corrections: Record<string, number> = {}
    for (const f of s.feedback) {
      const status = f.withdrawn_at ? 'withdrawn' : f.review_status
      counts[status]++
      if (f.review_status === 'approved' && !f.withdrawn_at) {
        const key = `${f.predicted_category}→${f.corrected_category}`
        corrections[key] = (corrections[key] ?? 0) + 1
      }
    }
    return clone({ feedback: rows.slice(offset, offset + limit), total: rows.length, counts, corrections }) as T
  }
  const withdrawMatch = url.pathname.match(/^\/api\/v1\/feedback\/([^/]+)\/withdraw$/)
  if (withdrawMatch && method === 'POST') {
    const f = s.feedback.find(f => f.operation_id === decodeURIComponent(withdrawMatch[1]!))
    if (!f) notFound()
    f.withdrawn_at = Math.floor(Date.now() / 1000)
    return clone({ status: 'withdrawn' }) as T
  }
  const reviewMatch = url.pathname.match(/^\/api\/v1\/feedback\/([^/]+)$/)
  if (reviewMatch && method === 'PUT') {
    const f = s.feedback.find(f => f.operation_id === decodeURIComponent(reviewMatch[1]!))
    if (!f) notFound()
    const status = (body as { review_status: 'approved' | 'rejected' }).review_status
    if (f.review_status !== 'pending_review' && f.review_status !== status) throw new Error('operation_conflict')
    f.review_status = status
    f.reviewed_by = 'demo-pixel8-7f21c4a9'
    f.reviewed_at ??= Math.floor(Date.now() / 1000)
    return clone(f) as T
  }
  const detailMatch = url.pathname.match(/^\/api\/v1\/messages\/([^/]+)$/)
  if (detailMatch && method === 'GET') {
    const target = s.messages.find(m => m.message_id === decodeURIComponent(detailMatch[1]!))
    if (!target) notFound()
    return clone(target) as T
  }

  if (url.pathname === '/api/v1/messages' && method === 'GET') {
    const cursor = Number(url.searchParams.get('cursor') ?? '0')
    const limit = Number(url.searchParams.get('limit') ?? '50')
    const rows = s.messages
      .filter((m) => m.revision > cursor)
      .sort((a, b) => a.revision - b.revision)
    const hasMore = rows.length > limit
    const page = hasMore ? rows.slice(0, limit) : rows
    const nextCursor = page.length > 0 ? page[page.length - 1]!.revision : cursor
    return clone({ messages: page, cursor: nextCursor, has_more: hasMore }) as T
  }

  const archiveMatch = url.pathname.match(/^\/api\/v1\/messages\/([^/]+)\/(archive|unarchive)$/)
  if (archiveMatch && method === 'POST') {
    const target = s.messages.find(m => m.message_id === decodeURIComponent(archiveMatch[1]!))
    if (!target) return notFound()
    const archived = archiveMatch[2] === 'archive'
    if (!!target.archived !== archived) { target.archived = archived; target.revision = ++s.revision }
    return clone(target) as T
  }
  const restoreMatch = url.pathname.match(/^\/api\/v1\/messages\/([^/]+)\/restore$/)
  if (restoreMatch && method === 'POST') {
    const target = s.messages.find((m) => m.message_id === decodeURIComponent(restoreMatch[1]!))
    if (!target) notFound()
    target.action = 'allow'
    target.reason = '用户恢复'
    target.restored = true
    target.archived = false
    target.revision = ++s.revision
    return clone(target) as T
  }

  const feedbackMatch = url.pathname.match(/^\/api\/v1\/messages\/([^/]+)\/feedback$/)
  if (feedbackMatch && method === 'POST') {
    const input = body as { operation_id: string; corrected_category: string }
    const existing = s.feedback.find(f => f.operation_id === input.operation_id)
    if (existing) return { status: existing.review_status } as T
    const message = s.messages.find(m => m.message_id === decodeURIComponent(feedbackMatch[1]!))
    if (!message) notFound()
    s.feedback.push({ ...input, message_id: message.message_id, predicted_category: message.category,
      model_version: message.model_version, review_status: 'pending_review' })
    return { status: 'pending_review' } as T
  }

  if (url.pathname === '/api/v1/filter/rules' && method === 'GET') {
    return clone(s.rules) as T
  }
  if (url.pathname === '/api/v1/filter/rules' && method === 'PUT') {
    s.rules = body as Rules
    return clone(s.rules) as T
  }

  if (url.pathname === '/api/v1/devices' && method === 'GET') {
    return clone(s.devices) as T
  }
  const deviceRoleMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/role$/)
  if (deviceRoleMatch && method === 'PUT') {
    const target = s.devices.find(d => d.device_id === decodeURIComponent(deviceRoleMatch[1]!))
    if (!target) notFound()
    target.role = (body as { role: 'admin' | 'editor' | 'viewer' }).role
    return clone(target) as T
  }
  const deviceMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)$/)
  if (deviceMatch && method === 'DELETE') {
    const target = s.devices.find((d) => d.device_id === decodeURIComponent(deviceMatch[1]!))
    if (!target) notFound()
    target.active = false
    return { revoked: true } as T
  }

  if (url.pathname === '/api/v1/devices/register' && method === 'POST') {
    const request = body as { device_id: string; name: string }
    if (!s.devices.some((d) => d.device_id === request.device_id)) {
      s.devices.push({
        device_id: request.device_id,
        name: request.name,
        public_key: 'mock-public-key',
        active: true,
        expires_at: Math.floor(Date.now() / 1000) + 90 * 24 * 3600,
      })
    }
    return { token: `mock-token-${Date.now()}`, device_id: request.device_id } as T
  }

  notFound()
}
