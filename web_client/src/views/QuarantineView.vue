<template>
  <div>
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="拦截只是应用层隔离：短信不会被删除，随时可以恢复；验证码与交易通知受保护规则约束，不会进入拦截箱。"
      style="margin-bottom: 14px"
    />

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">拦截总数</div>
        <div class="stat-value">{{ messages.summary?.quarantined ?? '—' }}</div>
        <div class="stat-hint">当前处于隔离状态的短信</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已人工恢复</div>
        <div class="stat-value">{{ restoredCount }}</div>
        <div class="stat-hint">经用户确认恢复到收件箱</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">拦截依据分布</div>
        <div class="stat-value" style="font-size: 15px">
          <div v-for="(count, reason) in reasonStats" :key="reason" class="muted">
            {{ reason }}：{{ count }} 条
          </div>
          <div v-if="Object.keys(reasonStats).length === 0" class="muted">—</div>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索发送方或正文" clearable style="width: 260px">
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <span class="toolbar-spacer" />
      <span class="muted">共 {{ total }} 条</span>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon style="margin-bottom: 14px">
      <el-button size="small" @click="reload">重试</el-button>
    </el-alert>
    <MessageTable
      :rows="rows"
      :loading="loading"
      show-restore
      empty-text="拦截箱是空的 —— 没有被隔离的短信"
      @select="openDetail"
      @restore="onRestore"
    />

    <div class="toolbar" style="margin-top: 14px; justify-content: flex-end">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50]" layout="total, sizes, prev, pager, next" background />
    </div>

    <MessageDetailDrawer
      v-model="drawerVisible"
      :message="detail"
      @restore="detail && onRestore(detail)"
      @feedback="onFeedback"
    />
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { ApiError } from '../api/client'
import type { Message } from '../api/types'
import MessageDetailDrawer from '../components/MessageDetailDrawer.vue'
import MessageTable from '../components/MessageTable.vue'
import { errorText } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { useMessageSearch } from '../composables/useMessageSearch'
import { useMessageActions } from '../composables/useMessageActions'

const messages = useMessagesStore()
const actions = useMessageActions()
const { keyword, page, pageSize, rows, total, loading, error, reload } = useMessageSearch('quarantine')
const restoredCount = computed(() => messages.summary?.restored ?? '—')
const reasonStats = computed(() => messages.summary?.quarantine_reasons ?? {})

const drawerVisible = ref(false)
const detail = ref<Message | null>(null)

function openDetail(message: Message): void {
  detail.value = message
  drawerVisible.value = true
}

async function onRestore(message: Message): Promise<void> {
  try {
    const updated = await actions.restore(message.message_id)
    void messages.pull().catch(() => {})
    await reload()
    if (detail.value?.message_id === updated.message_id) {
      detail.value = updated
    }
    ElMessage.success('已恢复到正常收件箱')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '恢复失败')
  }
}

async function onFeedback(category: string): Promise<void> {
  if (!detail.value) {
    return
  }
  try {
    await actions.feedback(detail.value.message_id, category)
    void messages.pull().catch(() => {})
    ElMessage.success('纠正类别已加密保存，原始模型预测保持不变')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '提交失败')
  }
}
</script>
