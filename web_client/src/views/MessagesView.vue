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

      <span class="toolbar-spacer" />

      <span class="muted">
        共 {{ filtered.length }} 条 / 全部 {{ messages.all.length }} 条
      </span>
      <el-button
        v-if="messages.hasMore"
        :loading="messages.loading"
        size="small"
        @click="() => messages.pull(400)"
      >
        加载更多历史
      </el-button>
    </div>

    <MessageTable
      :rows="paged"
      :loading="messages.loading && !messages.loaded"
      empty-text="没有符合条件的消息"
      @select="openDetail"
      @restore="onRestore"
    />

    <div class="toolbar" style="margin-top: 14px; justify-content: flex-end">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="filtered.length"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        background
      />
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
import { computed, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import { restoreMessage, sendFeedback } from '../api/endpoints'
import type { Message } from '../api/types'
import MessageDetailDrawer from '../components/MessageDetailDrawer.vue'
import MessageTable from '../components/MessageTable.vue'
import { errorText } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { CATEGORY_OPTIONS } from '../utils/format'
import { uuid } from '../utils/uuid'

const messages = useMessagesStore()

const keyword = ref('')
const categoryFilter = ref('')
const actionFilter = ref('')
const page = ref(1)
const pageSize = ref(20)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return messages.all.filter((message) => {
    if (categoryFilter.value && message.category !== categoryFilter.value) {
      return false
    }
    if (actionFilter.value && message.action !== actionFilter.value) {
      return false
    }
    if (
      kw &&
      !message.sender.toLowerCase().includes(kw) &&
      !message.body.toLowerCase().includes(kw)
    ) {
      return false
    }
    return true
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

watch([keyword, categoryFilter, actionFilter], () => {
  page.value = 1
})

const drawerVisible = ref(false)
const detail = ref<Message | null>(null)

function openDetail(message: Message): void {
  detail.value = message
  drawerVisible.value = true
}

async function onRestore(message: Message): Promise<void> {
  try {
    const updated = await restoreMessage(message.message_id, uuid())
    messages.upsert(updated)
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
    await sendFeedback(detail.value.message_id, uuid(), category)
    ElMessage.success('纠错已提交至待审核队列，不会直接改变当前分类')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '提交失败')
  }
}
</script>
