<template>
  <div class="feedback-view">
    <el-alert title="端到端加密消息的纠正类别仅保存在消息密文内，不会进入此服务器审核／导出队列，原始模型预测保持不变。" type="warning" :closable="false" show-icon style="margin-bottom: 14px" />
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
      <el-button v-if="auth.role === 'admin'" @click="exportDialog = true">导出已通过样本</el-button>
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
      <el-table-column label="操作" width="330" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="open(row.message_id)">查看短信</el-button>
          <el-button v-if="row.review_status !== 'withdrawn'" size="small" type="warning" :disabled="!!reviewing" @click="withdraw(row.operation_id)">撤回数据授权</el-button>
          <template v-if="row.review_status === 'pending_review' && auth.role === 'admin'">
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
          <el-button v-if="row.review_status !== 'withdrawn'" size="small" type="warning" :disabled="!!reviewing" @click="withdraw(row.operation_id)">撤回授权</el-button>
          <template v-if="row.review_status === 'pending_review' && auth.role === 'admin'">
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
    <el-dialog v-model="exportDialog" title="授权导出纠错样本" width="min(480px, 95vw)">
      <p>文件下载到本机，不会自动上传至分类器或训练服务。仅包含已通过审核的记录。</p>
      <el-select v-model="exportPurpose" aria-label="导出用途"><el-option value="evaluation" label="模型评估" /><el-option value="training" label="模型训练" /></el-select>
      <div class="export-options">
      <el-checkbox v-model="includeText">包含短信正文和发送方（敏感数据）</el-checkbox>
      <el-checkbox v-model="exportConsent">我已获得对应数据的使用授权，同意按所选用途导出</el-checkbox>
      </div>
      <template #footer><el-button @click="exportDialog = false">取消</el-button><el-button type="primary" :disabled="!exportConsent" :loading="exporting" @click="downloadExport">导出 JSON</el-button></template>
    </el-dialog>
    <MessageDetailDrawer v-model="drawer" :message="detail" :allow-actions="false" />
  </div>
</template>

<script setup lang="ts">
import { onScopeDispose, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api/client'
import { exportFeedback, getMessage, listFeedback, reviewFeedback, withdrawFeedback } from '../api/endpoints'
import type { FeedbackPage, ReviewStatus } from '../api/endpoints'
import type { Message } from '../api/types'
import { errorText } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { useAuthStore } from '../stores/auth'
import { categoryMeta, formatDateTime } from '../utils/format'
import MessageDetailDrawer from '../components/MessageDetailDrawer.vue'

const labels: Record<ReviewStatus, string> = { pending_review: '待审核', approved: '已通过', rejected: '已驳回', withdrawn: '已撤回' }
const categoryLabel = (category: string) => categoryMeta(category).label
const messages = useMessagesStore()
const auth = useAuthStore()
const filter = ref('pending_review'), page = ref(1), loading = ref(false), error = ref(''), reviewing = ref('')
const result = ref<FeedbackPage | null>(null), detail = ref<Message | null>(null), drawer = ref(false)
let generation = 0
let detailGeneration = 0
let disposed = false
let refreshPending = false

const exportDialog = ref(false), includeText = ref(false), exportConsent = ref(false), exporting = ref(false)
const exportPurpose = ref<'evaluation' | 'training'>('evaluation')
watch(exportDialog, () => { exportConsent.value = false; includeText.value = false })
async function downloadExport(): Promise<void> {
  if (!exportConsent.value || exporting.value) return
  exporting.value = true
  const purpose = exportPurpose.value, withText = includeText.value
  const session = messages.sessionVersion
  try {
    const samples: Record<string, unknown>[] = []
    let offset = 0
    for (;;) {
      const page = await exportFeedback(purpose, withText, offset)
      if (disposed || session !== messages.sessionVersion) return
      samples.push(...page.samples)
      if (!page.has_more) break
      offset = page.offset + 100
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schema_version: 1, purpose, include_text: withText, exported_at: new Date().toISOString(), samples }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url; link.download = `privrelay-feedback-${Date.now()}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    exportDialog.value = false
    ElMessage.success(`已导出 ${samples.length} 条样本`)
  } catch { ElMessage.error('导出失败，请重试') }
  finally { exporting.value = false }
}

async function load(): Promise<void> {
  if (disposed) return
  const request = ++generation
  refreshPending = false
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
    if (!disposed && request === generation) {
      loading.value = false
      if (refreshPending) void load()
    }
  }
}
async function open(id: string): Promise<void> {
  const request = ++detailGeneration
  try {
    const message = await getMessage(id)
    if (disposed || request !== detailGeneration) return
    detail.value = message
    drawer.value = true
  } catch { if (!disposed && request === detailGeneration) ElMessage.error('加载短信失败，请重试') }
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

async function withdraw(id: string): Promise<void> {
  try {
    await ElMessageBox.confirm('撤回后，该纠错样本将从后续导出中排除且无法恢复。已经下载的文件需要你自行删除。继续？', '撤回数据授权', { type: 'warning' })
    reviewing.value = id
    await withdrawFeedback(id)
    ElMessage.success('已撤回，后续导出将排除此样本')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof ApiError ? errorText(error.code) : '撤回失败，请重试')
  } finally { reviewing.value = '' }
}
watch(filter, () => { if (page.value !== 1) page.value = 1; else void load() }, { flush: 'sync' })
watch(page, () => void load(), { flush: 'sync' })
watch(() => messages.refreshVersion, () => {
  if (messages.lastSyncAt === null) return
  if (loading.value) refreshPending = true
  else void load()
})
watch(() => messages.sessionVersion, () => {
  result.value = null
  detail.value = null
  drawer.value = false
  detailGeneration++
  if (page.value !== 1) page.value = 1
  else void load()
}, { flush: 'sync' })

void load()
onScopeDispose(() => { disposed = true; generation++; detailGeneration++; result.value = null; detail.value = null })
</script>

<style scoped>
.feedback-cards { display: none; }
.export-options { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.export-options :deep(.el-checkbox) { height: auto; align-items: flex-start; margin-right: 0; }
.export-options :deep(.el-checkbox__label) { white-space: normal; line-height: 1.5; }
@media (max-width: 600px) {
  .feedback-table { display: none; }
  .feedback-cards { display: grid; gap: 10px; overflow-wrap: anywhere; }
  .feedback-view .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .feedback-view .stat-card { padding: 10px 8px; }
}
</style>
