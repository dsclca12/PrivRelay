import { ElMessage } from 'element-plus'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  clearSession,
  clearToken,
  getDeviceId,
  getDeviceName,
  getToken,
  setDeviceId,
  setDeviceName,
  setToken,
} from '../api/client'
import { createSession, deleteSession, getSession, registerDevice } from '../api/endpoints'
import router from '../router'
import { buildPairingRequest } from '../utils/pairing'
import { useMessagesStore } from './messages'

/** 服务端错误码 → 中文提示 */
const ERROR_TEXT: Record<string, string> = {
  pairing_rejected: '配对被拒绝：配对码错误、已过期或已被使用',
  restart_pairing_session: '失败次数过多，请重启服务端生成新的配对码',
  invalid_request: '请求格式错误',
  network_error: '无法连接服务器，请检查服务地址与网络',
  rules_contract: '规则参数不合法（模式 / 阈值 / 列表长度）',
  sender_length: '名单条目超过 128 字符',
  operation_conflict: '该操作已被其他请求修改，请刷新后重试',
  category: '纠错类别不合法',
}

export function errorText(code: string): string {
  return ERROR_TEXT[code] ?? `请求失败（${code}）`
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken() ?? '')
  const deviceId = ref(getDeviceId())
  const deviceName = ref(getDeviceName())
  let pendingPairToken: string | null = null
  const authenticated = ref(false)
  const paired = computed(() => authenticated.value)

  /** 使用服务端控制台输出的一次性配对码注册本浏览器 */
  async function pair(pairingCode: string, name: string): Promise<void> {
    if (pendingPairToken) {
      await useToken(pendingPairToken)
      pendingPairToken = null
      return
    }
    const request = await buildPairingRequest({ pairingCode, deviceName: name })
    const response = await registerDevice(request)
    // Keep the returned token in memory until session creation succeeds, so a
    // transient failure can be retried without consuming another pairing code.
    pendingPairToken = response.token
    setToken(response.token)
    await useToken(response.token, response.device_id)
    pendingPairToken = null
  }

  async function useToken(rawToken: string, _id = ''): Promise<void> {
    setToken(rawToken.trim())
    await createSession()
    const session = await getSession()
    deviceId.value = session.device_id
    deviceName.value = session.name
    setDeviceId(session.device_id)
    setDeviceName(session.name)
    clearToken()
    token.value = ''
    useMessagesStore().$reset()
    authenticated.value = true
  }

  async function restore(): Promise<boolean> {
    try {
      if (getToken()) await useToken(getToken()!)
      const session = await getSession()
      deviceId.value = session.device_id
      deviceName.value = session.name
      authenticated.value = true
      return true
    } catch {
      clearToken()
      authenticated.value = false
      return false
    }
  }

  /** 退出登录（保留服务端数据，仅清除本浏览器会话） */
  async function logout(options: { expired?: boolean } = {}): Promise<void> {
    if (!options.expired) {
      try { await deleteSession() } catch {
        ElMessage.error('退出失败，请检查连接后重试')
        return
      }
    }
    pendingPairToken = null
    useMessagesStore().$reset()
    authenticated.value = false
    token.value = ''
    deviceId.value = ''
    deviceName.value = ''
    clearSession()
    if (options.expired) {
      ElMessage.warning('访问令牌已失效，请重新配对本浏览器')
    }
    void router.replace('/login')
  }

  return { token, deviceId, deviceName, paired, pair, useToken, restore, logout }
})
