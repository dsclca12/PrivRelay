<template>
  <div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">本浏览器设备</div>
        <div class="stat-value" style="font-size: 15px">{{ auth.deviceName || '未命名' }}</div>
        <div class="stat-hint">
          <el-tooltip :content="auth.deviceId || '—'" placement="top">
            <span>{{ auth.deviceId ? shortId(auth.deviceId, 20) : '（手动令牌登录）' }}</span>
          </el-tooltip>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">服务端地址</div>
        <div class="stat-value" style="font-size: 15px">{{ serverAddress }}</div>
        <div class="stat-hint">控制台与 API 同源（开发环境经代理）</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已授权设备</div>
        <div class="stat-value">{{ activeCount }}</div>
        <div class="stat-hint">共 {{ devices.length }} 台（含已撤销）</div>
      </div>
    </div>

    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header>
        <span style="font-weight: 600">配对新设备</span>
      </template>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="生成二维码后，在安卓设置中扫码绑定；也可手动输入配对码。有效期 10 分钟，使用一次失效。"
        style="margin-bottom: 14px"
      />
      <div class="toolbar" style="margin-bottom: 12px">
        <el-select v-model="pairingRole" aria-label="新设备角色" style="width: 180px" :disabled="auth.role !== 'admin'">
          <el-option value="editor" label="编辑者（默认）" />
          <el-option value="viewer" label="只读查看者" />
          <el-option value="admin" label="管理员" />
        </el-select>
        <span class="muted">编辑者可同步和纠错；查看者只读；管理员可管理设备、规则和 AI 设置。</span>
      </div>
      <el-input v-model="phoneServer" :disabled="pairing" placeholder="手机可访问的服务器地址，如 https://relay.example.com" style="margin-bottom: 12px" @input="clearPairing" />
      <el-alert v-if="phoneServer.startsWith('http:')" type="warning" :closable="false" title="正式安卓客户端需要 HTTPS。HTTP 仅供 dev Debug 使用 ADB 回环测试（先执行 adb reverse tcp:8787 tcp:8787，并在手机勾选允许 HTTP）；局域网绑定请使用 HTTPS 地址。" style="margin-bottom: 12px" />
      <div class="toolbar" style="margin-bottom: 0">
        <el-button type="primary" :loading="pairing" :disabled="auth.role !== 'admin'" @click="handlePair">生成配对码</el-button>
        <el-input v-if="pairingCode" :model-value="pairingCode" readonly style="max-width: 480px" />
        <span v-if="pairingExpires" class="muted">有效至 {{ formatDateTime(pairingExpires * 1000) }}</span>
      </div>
      <img v-if="qrImage" :src="qrImage" alt="PrivRelay 一次性绑定二维码" style="display: block; width: 256px; max-width: 100%; margin-top: 14px" />
      <p v-if="qrImage" class="muted">请勿分享二维码；扫码后确认手机显示的服务器地址。</p>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="toolbar" style="margin-bottom: 0">
          <span style="font-weight: 600">已注册设备</span>
          <span class="toolbar-spacer" />
          <el-button size="small" :loading="loading" @click="() => load()">
            <el-icon style="margin-right: 4px"><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table v-loading="loading" :data="devices" row-key="device_id" stripe>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column label="角色" width="140">
          <template #default="{ row }">
            <el-select v-if="auth.role === 'admin'" :model-value="row.role || 'admin'" @change="value => onRoleChange(row, value)">
              <el-option value="admin" label="管理员" />
              <el-option value="editor" label="编辑者" />
              <el-option value="viewer" label="只读查看者" />
            </el-select>
            <el-tag v-else>{{ roleLabel(row.role || 'admin') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备 ID" min-width="200">
          <template #default="{ row }">
            <el-tooltip :content="row.device_id" placement="top">
              <span class="muted">{{ shortId(row.device_id, 24) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="公钥指纹（P-256）" min-width="200">
          <template #default="{ row }">
            <el-tooltip :content="row.public_key || '—'" placement="top">
              <span class="muted">{{ shortKey(row.public_key) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusOf(row).type" size="small" effect="light">
              {{ statusOf(row).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="令牌到期" width="170">
          <template #default="{ row }">{{ formatDateTime(row.expires_at * 1000) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="auth.role === 'admin'"
              size="small"
              type="danger"
              plain
              :disabled="!row.active"
              @click="onRevoke(row)"
            >
              撤销
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import QRCode from 'qrcode'
import { apiBase, ApiError } from '../api/client'
import { createPairingCode, getPairingStatus, listDevices, revokeDevice, setDeviceRole } from '../api/endpoints'
import { buildPairingQr } from '../utils/pairing'
import type { Device } from '../api/types'
import { errorText, useAuthStore } from '../stores/auth'
import { useLogsStore } from '../stores/logs'
import { formatDateTime, shortId, shortKey } from '../utils/format'

const auth = useAuthStore()
const logs = useLogsStore()

const devices = ref<Device[]>([])
const loading = ref(false)
const pairing = ref(false)
const pairingCode = ref('')
const pairingExpires = ref(0)
const qrImage = ref('')
const pairingRole = ref<'admin' | 'editor' | 'viewer'>('editor')
const phoneServer = ref(new URL(apiBase() || '/', location.href).origin)
let pairingTimer: ReturnType<typeof setInterval> | undefined
let disposed = false

function clearPairing(): void {
  pairingCode.value = ''
  pairingExpires.value = 0
  qrImage.value = ''
  clearInterval(pairingTimer)
}

async function checkPairing(): Promise<void> {
  const checkingCode = pairingCode.value
  if (pairingExpires.value * 1000 <= Date.now()) {
    clearPairing()
    return
  }
  try {
    const result = await getPairingStatus()
    if (disposed || !pairingCode.value || pairingCode.value !== checkingCode) return
    if (!result.active || result.expires_at !== pairingExpires.value) {
      clearPairing()
      await load()
    }
  } catch { /* 网络恢复后继续检查，过期时间仍在本地检查。 */ }
}

const serverAddress = apiBase() || `${location.host}（同源）`
const activeCount = computed(
  () => devices.value.filter((d) => d.active && d.expires_at * 1000 > Date.now()).length,
)
function roleLabel(role: string): string { return ({ admin: '管理员', editor: '编辑者', viewer: '只读查看者' } as Record<string, string>)[role] ?? '管理员' }

function statusOf(raw: unknown): { type: 'success' | 'warning' | 'info'; text: string } {
  const device = raw as Device
  if (!device.active) {
    return { type: 'info', text: '已撤销' }
  }
  if (device.expires_at * 1000 <= Date.now()) {
    return { type: 'warning', text: '已过期' }
  }
  return { type: 'success', text: '正常' }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    devices.value = await listDevices()
  } catch (error) {
    const message = error instanceof ApiError ? errorText(error.code) : '设备列表加载失败'
    ElMessage.error(message)
    logs.push('warn', `设备列表加载失败：${message}`)
  } finally {
    loading.value = false
  }
}

async function handlePair(): Promise<void> {
  pairing.value = true
  clearPairing()
  try {
    // Validate the address before invalidating the server's previous code.
    buildPairingQr(phoneServer.value, 'address-validation-only', Math.floor(Date.now() / 1000) + 600)
    const result = await createPairingCode(pairingRole.value)
    const image = await QRCode.toDataURL(buildPairingQr(phoneServer.value, result.pairing_code, result.expires_at), { width: 256, margin: 4 })
    if (disposed) return
    pairingCode.value = result.pairing_code
    pairingExpires.value = result.expires_at
    qrImage.value = image
    pairingTimer = setInterval(() => void checkPairing(), 3000)
    ElMessage.success('请使用安卓客户端扫码绑定')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : error instanceof Error ? error.message : '生成配对码失败')
  } finally {
    pairing.value = false
  }
}

async function onRoleChange(raw: unknown, value: unknown): Promise<void> {
  const device = raw as Device
  if (!['admin', 'editor', 'viewer'].includes(String(value))) return
  try {
    await setDeviceRole(device.device_id, value as 'admin' | 'editor' | 'viewer')
    ElMessage.success('设备角色已更新')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '更新设备角色失败')
    await load()
  }
}

async function onRevoke(raw: unknown): Promise<void> {
  const device = raw as Device
  const isSelf = device.device_id === auth.deviceId
  try {
    await ElMessageBox.confirm(
      isSelf
        ? '这将是本浏览器的会话，撤销后当前页面会立即失去访问权限并回到登录页。'
        : `撤销后「${device.name}」将立即失去访问权限，需要重新配对才能继续使用。`,
      '撤销设备授权',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await revokeDevice(device.device_id)
    logs.push('info', `已撤销设备授权：${device.name}`)
    ElMessage.success('设备授权已撤销')
    if (isSelf) {
      auth.logout({ expired: true })
      return
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '撤销失败')
  }
}

onMounted(() => {
  void load()
})
onBeforeUnmount(() => { disposed = true; clearPairing() })
</script>
