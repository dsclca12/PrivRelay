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
        title="生成一次性配对码，在手机或另一浏览器中输入。有效期 10 分钟；生成新码会使旧码失效。"
        style="margin-bottom: 14px"
      />
      <div class="toolbar" style="margin-bottom: 0">
        <el-button type="primary" :loading="pairing" @click="handlePair">生成配对码</el-button>
        <el-input v-if="pairingCode" :model-value="pairingCode" readonly style="max-width: 480px" />
        <span v-if="pairingExpires" class="muted">有效至 {{ formatDateTime(pairingExpires * 1000) }}</span>
      </div>
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
import { computed, onMounted, ref } from 'vue'
import { apiBase, ApiError } from '../api/client'
import { createPairingCode, listDevices, revokeDevice } from '../api/endpoints'
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

const serverAddress = apiBase() || `${location.host}（同源）`
const activeCount = computed(
  () => devices.value.filter((d) => d.active && d.expires_at * 1000 > Date.now()).length,
)

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
  try {
    const result = await createPairingCode()
    pairingCode.value = result.pairing_code
    pairingExpires.value = result.expires_at
    ElMessage.success('请在新设备中输入配对码')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '生成配对码失败')
  } finally {
    pairing.value = false
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
</script>
