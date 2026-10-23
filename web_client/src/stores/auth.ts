import { ElMessage } from 'element-plus'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  clearSession,
  clearToken,
  ApiError,
  getDeviceId,
  getDeviceName,
  getToken,
  setDeviceId,
  setDeviceName,
  setToken,
} from '../api/client'
import { createSession, deleteSession, getSession, getVaultParams, listMessages, registerDevice } from '../api/endpoints'
import router from '../router'
import { buildPairingRequest } from '../utils/pairing'
import { useMessagesStore } from './messages'
import { clearVaultCredentials, hasVaultCredentials, setVaultCredentials, vaultGeneration } from '../utils/vault'

/** 服务端错误码 → 中文提示 */
const ERROR_TEXT: Record<string, string> = {
  pairing_rejected: '配对被拒绝：配对码错误、已过期或已被使用',
  restart_pairing_session: '失败次数过多，请重启服务端生成新的配对码',
  invalid_request: '请求格式错误',
  network_error: '无法连接服务器，请检查服务地址与网络',
  rules_contract: '规则参数不合法（模式 / 阈值 / 列表长度）',
  sender_length: '名单条目超过 128 字符',
  operation_conflict: '该操作已被其他请求修改，请刷新后重试',
  insufficient_role: '当前账号角色没有执行此操作的权限',
  last_admin: '至少需要保留一个有效管理员',
  role_contract: '设备角色值无效',
  consent_withdrawn: '该样本的授权已撤回',
  category: '纠错类别不合法',
}

export function errorText(code: string): string {
  return ERROR_TEXT[code] ?? `请求失败（${code}）`
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken() ?? '')
  const deviceId = ref(getDeviceId())
  const deviceName = ref(getDeviceName())
  const role = ref<'admin' | 'editor' | 'viewer'>('viewer')
  let pendingPairToken: string | null = null
  let pendingVaultPassphrase = ''
  let authenticationGeneration = 0
  let loginPending = false
  const authenticated = ref(false)
  const paired = computed(() => authenticated.value)

  /** 使用服务端控制台输出的一次性配对码注册本浏览器 */
  async function pair(pairingCode: string, name: string, passphrase: string): Promise<void> {
    if (pendingPairToken) {
      pendingVaultPassphrase = passphrase
      await useToken(pendingPairToken, '', pendingVaultPassphrase)
      pendingPairToken = null
      pendingVaultPassphrase = ''
      return
    }
    const phrase = passphrase.trim()
    if (phrase.length < 12 || [...phrase].some((c) => c.charCodeAt(0) < 33 || c.charCodeAt(0) > 126)) throw new Error('端到端加密口令至少 12 个字符，且只能包含可见 ASCII 字符')
    const request = await buildPairingRequest({ pairingCode, deviceName: name })
    const response = await registerDevice(request)
    // Keep the returned token in memory until session creation succeeds, so a
    // transient failure can be retried without consuming another pairing code.
    pendingPairToken = response.token
    pendingVaultPassphrase = passphrase
    setToken(response.token)
    await useToken(response.token, response.device_id, passphrase)
    pendingPairToken = null
    pendingVaultPassphrase = ''
  }

  async function useToken(rawToken: string, _id = '', passphrase?: string): Promise<void> {
    if (loginPending) throw new Error('正在验证登录，请稍候')
    loginPending = true
    const attempt = ++authenticationGeneration
    const checkAttempt = () => { if (attempt !== authenticationGeneration) throw new Error('登录会话已变更，请重试') }
    authenticated.value = false
    clearVaultCredentials()
    useMessagesStore().$reset()
    try {
      setToken(rawToken.trim())
      await createSession()
      checkAttempt()
      const session = await getSession()
      checkAttempt()
      const vaultPhrase = passphrase ?? window.prompt('输入端到端加密口令（至少 12 个字符）') ?? ''
      const params = await getVaultParams()
      checkAttempt()
      setVaultCredentials(vaultPhrase, params)
      await verifyVaultCredentials()
      checkAttempt()
      deviceId.value = session.device_id
      deviceName.value = session.name
      role.value = session.role
      setDeviceId(session.device_id)
      setDeviceName(session.name)
      clearToken()
      token.value = ''
      useMessagesStore().$reset()
      authenticated.value = true
    } catch (error) {
      if (attempt === authenticationGeneration) {
        clearVaultCredentials()
        authenticated.value = false
      }
      throw error
    } finally { loginPending = false }
  }

  async function verifyVaultCredentials(): Promise<void> {
    const session = vaultGeneration()
    try {
      // listMessages authenticates and decrypts the first existing ciphertext.
      // An empty vault has no record against which to verify a first key.
      await listMessages(0, 1)
      if (session !== vaultGeneration()) throw new Error('vault_session_changed')
    } catch (error) {
      if (session === vaultGeneration()) clearVaultCredentials()
      if (error instanceof ApiError) throw error
      throw new Error('端到端加密口令与已有消息不匹配，或加密记录已损坏，请检查共享口令后重试')
    }
  }

  async function restore(): Promise<boolean> {
    if (loginPending) return false
    if (getToken()) {
      try { await useToken(getToken()!); return true } catch { return false }
    }
    const attempt = ++authenticationGeneration
    try {
      const session = await getSession()
      if (attempt !== authenticationGeneration) return false
      if (!hasVaultCredentials()) {
        const phrase = window.prompt('输入端到端加密口令（至少 12 个字符）')
        if (!phrase) return false
        const params = await getVaultParams()
        if (attempt !== authenticationGeneration) return false
        setVaultCredentials(phrase, params)
        await verifyVaultCredentials()
      }
      if (attempt !== authenticationGeneration) return false
      deviceId.value = session.device_id
      deviceName.value = session.name
      role.value = session.role
      authenticated.value = true
      return true
    } catch {
      if (attempt === authenticationGeneration) {
        clearToken()
        clearVaultCredentials()
        authenticated.value = false
      }
      return false
    }
  }

  /** 退出登录（保留服务端数据，仅清除本浏览器会话） */
  async function logout(options: { expired?: boolean } = {}): Promise<void> {
    authenticationGeneration++
    if (!options.expired) {
      try { await deleteSession() } catch {
        ElMessage.error('退出失败，请检查连接后重试')
        return
      }
    }
    pendingPairToken = null
    pendingVaultPassphrase = ''
    useMessagesStore().$reset()
    authenticated.value = false
    token.value = ''
    deviceId.value = ''
    deviceName.value = ''
    role.value = 'viewer'
    clearSession()
    clearVaultCredentials()
    if (options.expired) {
      ElMessage.warning('访问令牌已失效，请重新配对本浏览器')
    }
    void router.replace('/login')
  }

  return { token, deviceId, deviceName, role, paired, pair, useToken, restore, logout }
})
