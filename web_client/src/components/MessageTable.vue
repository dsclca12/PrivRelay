<template>
  <el-table
    v-loading="loading"
    class="message-table"
    :data="rows"
    row-key="message_id"
    stripe
    :empty-text="emptyText"
    @row-click="onRowClick"
  >
    <el-table-column label="时间" width="160">
      <template #default="{ row }">{{ formatDateTime(row.received_at) }}</template>
    </el-table-column>

    <el-table-column label="发送方" width="170">
      <template #default="{ row }">
        <div class="sender-cell">
          <span>{{ row.sender }}</span>
          <el-tag
            v-if="row.subscription_id > 0"
            class="sim-tag"
            size="small"
            type="info"
            effect="plain"
          >
            SIM{{ row.subscription_id }}
          </el-tag>
        </div>
      </template>
    </el-table-column>

    <el-table-column prop="body" label="正文" min-width="300" show-overflow-tooltip />

    <el-table-column label="分类" width="120">
      <template #default="{ row }">
        <el-tag :type="categoryMeta(row.category).tagType" size="small" effect="light">
          <span class="tag-content">
            <el-icon><component :is="categoryMeta(row.category).icon" /></el-icon>
            {{ categoryMeta(row.category).label }}
          </span>
        </el-tag>
      </template>
    </el-table-column>

    <el-table-column label="置信度" width="90" align="center">
      <template #default="{ row }">
        <span v-if="row.classified">{{ formatPercent(row.confidence) }}</span>
        <span v-else class="muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="风险" width="90" align="center">
      <template #default="{ row }">
        <span v-if="row.classified">{{ formatPercent(row.risk) }}</span>
        <span v-else class="muted">—</span>
      </template>
    </el-table-column>

    <el-table-column label="处理" width="100">
      <template #default="{ row }">
        <el-tag :type="actionMeta(row.action).tagType" size="small" effect="light">
          <span class="tag-content">
            <el-icon><component :is="actionMeta(row.action).icon" /></el-icon>
            {{ actionMeta(row.action).label }}
          </span>
        </el-tag>
      </template>
    </el-table-column>

    <el-table-column prop="reason" label="依据" width="190" show-overflow-tooltip />

    <el-table-column label="来源设备" width="140">
      <template #default="{ row }">
        <el-tooltip :content="row.device_id" placement="top">
          <span>{{ shortId(row.device_id) }}</span>
        </el-tooltip>
      </template>
    </el-table-column>

    <el-table-column v-if="showRestore" label="操作" width="110" fixed="right">
      <template #default="{ row }">
        <el-popconfirm
          title="恢复到正常收件箱？"
          confirm-button-text="恢复"
          cancel-button-text="取消"
          @confirm="requestRestore(row)"
        >
          <template #reference>
            <el-button size="small" type="primary" plain @click.stop>恢复</el-button>
          </template>
        </el-popconfirm>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import type { Message } from '../api/types'
import { actionMeta, categoryMeta, formatDateTime, formatPercent, shortId } from '../utils/format'

interface Props {
  rows: Message[]
  loading?: boolean
  showRestore?: boolean
  emptyText?: string
}

withDefaults(defineProps<Props>(), {
  loading: false,
  showRestore: false,
  emptyText: '暂无消息',
})

const emit = defineEmits<{
  select: [message: Message]
  restore: [message: Message]
}>()

function onRowClick(row: Message): void {
  emit('select', row)
}

/** 表格 slot 行类型为 DefaultRow，运行期再收窄为 Message */
function requestRestore(raw: unknown): void {
  emit('restore', raw as Message)
}
</script>
