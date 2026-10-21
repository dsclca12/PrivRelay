<template>
  <div class="feedback-view">
    <el-alert title="审核仅记录纠错结论，不改变短信分类或模型，不自动发送至分类服务。用于模型评估或训练仍需单独授权。"
      type="info" :closable="false" show-icon style="margin-bottom: 14px" />
    <div class="stat-grid">
      <div v-for="(label, key) in labels" :key="key" class="stat-card">
        <div class="stat-label">{{ label }}</div>
        <div class="stat-value">{{ result?.counts[key] ?? '—' }}</div>
      </div>
    </div>
    <div class="toolbar">
      <el-select v-model="filter" style="width: 150px" aria-label="审核状态">
        <el-option value="" label="全部状态" />
        <el-option v-for="(label, key) in labels" :key="key" :value="key" :label="label" />
      </el-select>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom: 14px" />
    <el-table class="feedback-table" v-loading="loading" :data="result?.feedback ?? []" row-key="operation_id" empty-text="暂无纠错记录">
      <el-table-column label="原预测 → 纠正类别" min-width="210">
        <template #default="{ row }">{{ categoryLabel(row.predicted_category || 'uncertain') }} → {{ categoryLabel(row.corrected_category) }}</template>
      </el-table-column>
      <el-table-column prop="model_version" label="模型版本" min-width="160" />
      <el-table-column label="审核状态" width="110">
        <template #default="{ row }">{{ labels[row.review_status as ReviewStatus] }}</template>
      </el-table-column>
      <el-table-column label="审核记录" min-width="210">
        <template #default="{ row }">
          <span v-if="row.reviewed_at">{{ formatDateTime(row.reviewed_at * 1000) }} · {{ row.reviewed_by }}</span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="open(row.message_id)">查看短信</el-button>
          <template v-if="row.review_status === 'pending_review'">
            <el-button size="small" type="success" :disabled="!!reviewing" @click="review(row.operation_id, 'approved')">通过</el-button>
            <el-button size="small" type="danger" :disabled="!!reviewing" @click="review(row.operation_id, 'rejected')">驳回</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <div class="feedback-cards" v-loading="loading">
      <el-card v-for="row in result?.feedback ?? []" :key="row.operation_id" shadow="never">
        <div>{{ categoryLabel(row.predicted_category || 'uncertain') }} → {{ categoryLabel(row.corrected_category) }}</div>
        <div class="muted">{{ labels[row.review_status] }} · {{ row.model_version || '无模型版本' }}</div>
        <div v-if="row.reviewed_at" class="muted">
          {{ formatDateTime(row.reviewed_at * 1000) }}<br />{{ row.reviewed_by }}
        </div>
        <div class="drawer-actions">
          <el-button size="small" @click="open(row.message_id)">查看短信</el-button>
          <template v-if="row.review_status === 'pending_review'">
            <el-button size="small" type="success" :disabled="!!reviewing" @click="review(row.operation_id, 'approved')">通过</el-button>
            <el-button size="small" type="danger" :disabled="!!reviewing" @click="review(row.operation_id, 'rejected')">驳回</el-button>
          </template>
        </div>
      </el-card>
      <el-empty v-if="!result?.feedback.length && !loading" description="暂无纠错记录" />
    </div>
    <div class="toolbar" style="margin-top: 14px; justify-content: flex-end">
      <el-pagination v-model:current-page="page" :page-size="20" :total="result?.total ?? 0" layout="total, prev, pager, next" background />
    </div>
    <el-card v-if="result && Object.keys(result.corrections).length" shadow="never">
      <template #header>已通过纠错分布（纠错记录数）</template>
      <div v-for="(count, pair) in result.corrections" :key="pair">
        {{ String(pair).split('→').map(categoryLabel).join(' → ') }}：{{ count }}
      </div>
    </el-card>
    <MessageDetailDrawer v-model="drawer" :message="detail" :allow-actions="false" />
  </div>
</template>

<script setup lang="ts">
import { onScopeDispose, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api/client'
import { getMessage, listFeedback, reviewFeedback } from '../api/endpoints'
import type { FeedbackPage, ReviewStatus } from '../api/endpoints'
import type { Message } from '../api/types'
import { errorText } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { categoryMeta, formatDateTime } from '../utils/format'
import MessageDetailDrawer from '../components/MessageDetailDrawer.vue'

const labels: Record<ReviewStatus, string> = { pending_review: '待审核', approved: '已通过', rejected: '已驳回' }
const categoryLabel = (category: string) => categoryMeta(category).label
const messages = useMessagesStore()
const filter = ref('pending_review'), page = ref(1), loading = ref(false), error = ref(''), reviewing = ref('')
const result = ref<FeedbackPage | null>(null), detail = ref<Message | null>(null), drawer = ref(false)
let generation = 0
let detailGeneration = 0
let disposed = false

async function load(): Promise<void> {
  const request = ++generation
  loading.value = true
  error.value = ''
  try {
    const value = await listFeedback(filter.value, (page.value - 1) * 20)
    if (disposed || request !== generation) return
    const last = Math.max(1, Math.ceil(value.total / 20))
    if (page.value > last) { page.value = last; return }
    result.value = value
  } catch (e) {
    if (!disposed && request === generation) error.value = e instanceof ApiError ? errorText(e.code) : '加载失败，请重试'
  } finally {
    if (!disposed && request === generation) loading.value = false
  }
}
async function open(id: string): Promise<void> {
  const request = ++detailGeneration
  try {
    const message = await getMessage(id)
    if (disposed || request !== detailGeneration) return
    detail.value = message
    drawer.value = true
  } catch { if (!disposed) ElMessage.error('加载短信失败，请重试') }
}
async function review(id: string, status: 'approved' | 'rejected'): Promise<void> {
  if (reviewing.value) return
  reviewing.value = id
  try {
    await ElMessageBox.confirm(`确认${status === 'approved' ? '通过' : '驳回'}这条纠错？审核后不能更改结论。`, '审核纠错', {
      confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning',
    })
    if (disposed) return
    await reviewFeedback(id, status)
    await load()
    void messages.pull().catch(() => {})
    ElMessage.success('审核已保存')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close' && !disposed) {
      ElMessage.error(e instanceof ApiError ? errorText(e.code) : '审核失败，请重试')
      await load()
    }
  } finally { reviewing.value = '' }
}
watch(filter, () => { if (page.value !== 1) page.value = 1; else void load() })
watch([page, () => messages.refreshVersion], () => void load())
void load()
onScopeDispose(() => { disposed = true; generation++; detailGeneration++; result.value = null; detail.value = null })
</script>

<style scoped>
.feedback-cards { display: none; }
@media (max-width: 600px) {
  .feedback-table { display: none; }
  .feedback-cards { display: grid; gap: 10px; overflow-wrap: anywhere; }
  .feedback-view .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .feedback-view .stat-card { padding: 10px 8px; }
}
</style>
