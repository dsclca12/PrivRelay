<template>
  <div>
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="搜索发送方或正文"
        clearable
        style="width: 260px"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>

      <el-select v-model="categoryFilter" placeholder="全部分类" clearable style="width: 150px">
        <el-option
          v-for="option in CATEGORY_OPTIONS"
          :key="option.value"
          :value="option.value"
          :label="option.label"
        />
      </el-select>

      <el-select v-model="actionFilter" placeholder="全部处理" style="width: 130px">
        <el-option value="" label="全部处理" />
        <el-option value="allow" label="正常" />
        <el-option value="quarantine" label="拦截" />
      </el-select>

      <el-select v-model="archivedFilter" aria-label="归档状态" style="width: 130px">
        <el-option value="false" label="未归档" /><el-option value="true" label="已归档" /><el-option value="all" label="全部归档状态" />
      </el-select>
      <span class="toolbar-spacer" />

      <span class="muted">共 {{ total }} 条</span>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon style="margin-bottom: 14px">
      <el-button size="small" @click="reload">重试</el-button>
    </el-alert>
    <MessageTable
      :rows="rows"
      :loading="loading"
      empty-text="没有符合条件的消息"
      @select="openDetail"
      @restore="onRestore"
    />

    <div class="toolbar" style="margin-top: 14px; justify-content: flex-end">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50]"
        layout="total, sizes, prev, pager, next"
        background
      />
    </div>

    <MessageDetailDrawer
      v-model="drawerVisible"
      :message="detail"
      :allow-archive="true"
      @restore="detail && onRestore(detail)"
      @feedback="onFeedback"
      @archive="onArchive"
    />
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { ApiError } from '../api/client'

import type { Message } from '../api/types'
import MessageDetailDrawer from '../components/MessageDetailDrawer.vue'
import MessageTable from '../components/MessageTable.vue'
import { errorText } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { useMessageSearch } from '../composables/useMessageSearch'
import { CATEGORY_OPTIONS } from '../utils/format'
import { useMessageActions } from '../composables/useMessageActions'

const messages = useMessagesStore()
const actions = useMessageActions()

const { keyword, categoryFilter, actionFilter, archivedFilter, page, pageSize, rows, total, loading, error, reload } = useMessageSearch()

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

async function onArchive(): Promise<void> {
  if (!detail.value) return
  try {
    const updated = await actions.archive(detail.value.message_id, !detail.value.archived)
    if (detail.value?.message_id === updated.message_id) detail.value = updated
    await reload()
    void messages.pull().catch(() => {})
    ElMessage.success(updated.archived ? '已归档' : '已取消归档')
  } catch { ElMessage.error('归档操作失败，请重试') }
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
