<template>
  <div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">服务端状态</div>
        <div class="stat-value">
          <el-tag :type="health?.status === 'ok' ? 'success' : 'danger'" effect="light">
            {{ health?.status === 'ok' ? '正常' : health ? '异常' : '检测中…' }}
          </el-tag>
        </div>
        <div class="stat-hint">GET /healthz · 每 10 秒检测</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">分类服务</div>
        <div class="stat-value">
          <el-tag :type="classifierMeta.type" effect="light">{{ classifierMeta.text }}</el-tag>
        </div>
        <div class="stat-hint">PrivateSMS-Classifier 健康状态</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">消息同步</div>
        <div class="stat-value">
          <el-tag :type="syncMeta.type" effect="light">{{ syncMeta.text }}</el-tag>
        </div>
        <div class="stat-hint">
          最近同步 {{ lastSyncAt ? formatClock(lastSyncAt) : '—' }}
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-label">消息总数</div>
        <div class="stat-value">{{ messages.all.length }}</div>
        <div class="stat-hint">服务端修订号 {{ messages.cursor }}</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">拦截 / 已恢复</div>
        <div class="stat-value">
          {{ messages.quarantined.length }} / {{ restoredCount }}
        </div>
        <div class="stat-hint">拦截均可恢复，首版不执行删除</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">已授权设备</div>
        <div class="stat-value">{{ deviceCount }}</div>
        <div class="stat-hint">未撤销且令牌未过期</div>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="服务端暂未提供「在线设备数」接口，此处统计的是已授权设备；实时推送依赖服务端 WebSocket 鉴权改造，未就绪时前端自动降级为 5 秒轮询，功能不受影响。"
    />

    <el-card shadow="never">
      <template #header>
        <div class="toolbar" style="margin-bottom: 0">
          <span style="font-weight: 600">本地运行日志</span>
          <span class="muted">不包含短信正文、发送方与验证码</span>
          <span class="toolbar-spacer" />
          <el-button size="small" :disabled="logs.entries.length === 0" @click="logs.clear()">
            清空
          </el-button>
        </div>
      </template>

      <el-table :data="logs.entries" row-key="id" size="small" :empty-text="'暂无日志'">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatDateTime(row.ts) }}</template>
        </el-table-column>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'"
              size="small"
              effect="plain"
            >
              {{ row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="text" label="内容" min-width="320" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError } from '../api/client'
import { getHealth, listDevices } from '../api/endpoints'
import type { Device, Health } from '../api/types'
import { useSync } from '../composables/useSync'
import { useLogsStore } from '../stores/logs'
import { useMessagesStore } from '../stores/messages'
import { formatClock, formatDateTime } from '../utils/format'

const messages = useMessagesStore()
const logs = useLogsStore()
const { status: syncStatus, lastSyncAt } = useSync()

const health = ref<Health | null>(null)
const devices = ref<Device[]>([])
let timer: ReturnType<typeof setInterval> | null = null

const restoredCount = computed(() => messages.all.filter((m) => m.restored).length)
const deviceCount = computed(
  () => devices.value.filter((d) => d.active && d.expires_at * 1000 > Date.now()).length,
)

const classifierMeta = computed<{ type: 'success' | 'warning' | 'info' | 'danger'; text: string }>(() => {
  if (!health.value) {
    return { type: 'info', text: '检测中…' }
  }
  if (health.value.classifier === 'ok') {
    return { type: 'success', text: '正常' }
  }
  if (health.value.classifier === 'unavailable') {
    return { type: 'warning', text: '不可用（Fail-open）' }
  }
  return { type: 'info', text: '未配置' }
})

const syncMeta = computed<{ type: 'success' | 'warning' | 'info'; text: string }>(() => {
  switch (syncStatus.value) {
    case 'live':
      return { type: 'success', text: '实时推送' }
    case 'connecting':
      return { type: 'info', text: '连接中…' }
    case 'polling':
      return { type: 'warning', text: '轮询同步（5 秒）' }
    default:
      return { type: 'info', text: '已停止' }
  }
})

async function probe(): Promise<void> {
  try {
    health.value = await getHealth()
  } catch (error) {
    health.value = null
    if (error instanceof ApiError && error.code !== 'network_error') {
      logs.push('warn', `健康检查失败：${error.code}`)
    }
  }
  try {
    devices.value = await listDevices()
  } catch {
    // 列表失败不打扰，下次探测重试
  }
}

onMounted(() => {
  void probe()
  timer = setInterval(() => void probe(), 10000)
})

onBeforeUnmount(() => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<style scoped>
/* 监控页卡片标签与数值对齐 */
.stat-value .el-tag {
  vertical-align: middle;
}
</style>
