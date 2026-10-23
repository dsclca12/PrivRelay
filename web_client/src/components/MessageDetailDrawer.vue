<template>
  <el-drawer v-model="visible" title="短信详情" size="min(520px, 100vw)">
    <div v-if="message" class="detail-body">
      <div class="toolbar" style="margin-bottom: 4px">
        <el-tag :type="categoryMeta(message.category).tagType" effect="light">
          <span class="tag-content">
            <el-icon><component :is="categoryMeta(message.category).icon" /></el-icon>
            {{ categoryMeta(message.category).label }}
          </span>
        </el-tag>
        <el-tag :type="actionMeta(message.action).tagType" effect="light">
          <span class="tag-content">
            <el-icon><component :is="actionMeta(message.action).icon" /></el-icon>
            {{ actionMeta(message.action).label }}
          </span>
        </el-tag>
        <el-tag v-if="message.restored" size="small" type="info" effect="plain">已人工恢复</el-tag>
      </div>

      <div class="message-text">{{ message.body }}</div>
      <div v-if="message.content_kind === 'mms' || message.attachments?.length" class="mms-attachments">
        <div v-for="(attachment, index) in message.attachments ?? []" :key="`${message.message_id}-${index}`" class="mms-attachment">
          <img v-if="attachment.mime_type.startsWith('image/')" :src="attachmentUrl(attachment)" :alt="attachment.filename" class="mms-image">
          <a v-else :href="attachmentUrl(attachment)" :download="safeFilename(attachment.filename)">{{ attachment.filename }} · {{ attachment.mime_type }} · {{ attachment.size }} bytes</a>
        </div>
        <p v-if="!message.attachments?.length && !message.attachments_truncated" class="muted">此彩信没有可显示的附件</p>
        <el-alert v-if="message.attachments_truncated" type="warning" :closable="false" title="部分彩信附件超过 Android 端 2 MiB 同步上限，仅保存在系统短信存储中。" />
      </div>
      <p v-if="message.corrected_category" class="muted">用户纠正：{{ categoryMeta(message.corrected_category).label }}（原始模型预测保持不变）</p>

      <el-alert
        v-if="!message.classified"
        type="info"
        :closable="false"
        show-icon
        title="分类服务不可用，已按 Fail-open 策略正常保留；服务端恢复后会自动补分类。"
      />

      <div class="detail-section-title">策略依据</div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="处理动作">
          {{ actionMeta(message.action).label }}
        </el-descriptions-item>
        <el-descriptions-item label="依据">{{ message.reason }}</el-descriptions-item>
        <el-descriptions-item label="置信度">
          {{ message.classified ? formatPercent(message.confidence) : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="风险评分">
          {{ message.classified ? formatPercent(message.risk) : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="需人工复核">
          {{ message.needs_review ? '是' : '否' }}
        </el-descriptions-item>
        <el-descriptions-item label="分类来源">{{ message.classification_source === 'llm' ? 'LLM' : '轻量分类器' }}{{ message.llm_pending ? ' · 等待 LLM 复核' : '' }}</el-descriptions-item>
        <el-descriptions-item v-if="message.primary_classification" label="轻量模型原始分类">{{ categoryMeta(message.primary_classification.category).label }} · {{ message.primary_classification.model_version }}</el-descriptions-item>
        <el-descriptions-item label="模型版本">
          {{ message.model_version || '—' }}
        </el-descriptions-item>
        <el-descriptions-item v-if="message.classifier_action" label="分类器决策">
          {{ message.classifier_action === 'block' ? '建议隔离' : '正常保留' }}
        </el-descriptions-item>
        <el-descriptions-item v-if="message.classifier_reason" label="分类器依据">
          {{ message.classifier_reason }}
        </el-descriptions-item>
        <el-descriptions-item v-if="message.classifier_threshold !== undefined" label="决策实际阈值">
          {{ formatPercent(message.classifier_threshold) }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="detail-section-title">消息元数据</div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="接收时间">
          {{ formatDateTime(message.received_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="发送方">{{ message.sender }}</el-descriptions-item>
        <el-descriptions-item label="SIM / 槽位">
          {{ message.subscription_id > 0 ? `SIM${message.subscription_id}（槽位 ${message.slot}）` : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="来源设备">
          <el-tooltip :content="message.device_id" placement="top">
            <span>{{ shortId(message.device_id, 16) }}</span>
          </el-tooltip>
        </el-descriptions-item>
        <el-descriptions-item label="服务端修订号">{{ message.revision }}</el-descriptions-item>
        <el-descriptions-item label="消息 ID">
          <el-tooltip :content="message.message_id" placement="top">
            <span>{{ shortId(message.message_id, 16) }}</span>
          </el-tooltip>
        </el-descriptions-item>
      </el-descriptions>

      <template v-if="allowActions">
      <div class="detail-section-title">操作</div>
      <div class="drawer-actions">
        <el-button v-if="allowArchive" @click="emit('archive')">{{ message.archived ? '取消归档' : '归档消息' }}</el-button>
        <el-button
          v-if="message.action === 'quarantine'"
          type="primary"
          @click="emit('restore')"
        >
          <el-icon style="margin-right: 4px"><RefreshLeft /></el-icon>
          恢复到正常收件箱
        </el-button>
      </div>

      <div class="detail-section-title">分类纠错</div>
      <div class="drawer-actions">
        <el-select
          v-model="corrected"
          placeholder="选择正确分类"
          clearable
          style="width: 200px"
        >
          <el-option
            v-for="option in CATEGORY_OPTIONS"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          />
        </el-select>
        <el-button type="primary" plain :disabled="!corrected" @click="submitFeedback">
          提交纠错
        </el-button>
      </div>
      <p class="muted" style="margin-top: 8px">
        纠正类别保存在消息密文内，不改变原始模型预测，也不发送到服务端审核队列。
      </p>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Message } from '../api/types'
import { CATEGORY_OPTIONS, actionMeta, categoryMeta, formatDateTime, formatPercent, shortId } from '../utils/format'

interface Props {
  allowArchive?: boolean
  modelValue: boolean
  message: Message | null
  allowActions?: boolean
}

const props = withDefaults(defineProps<Props>(), { allowActions: true })

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  archive: []
  restore: []
  feedback: [category: string]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const corrected = ref('')

watch(
  () => props.message?.message_id,
  () => {
    corrected.value = ''
  },
)

function submitFeedback(): void {
  if (!corrected.value) {
    return
  }
  emit('feedback', corrected.value)
  corrected.value = ''
}

function attachmentUrl(attachment: NonNullable<Message['attachments']>[number]): string {
  return `data:${attachment.mime_type};base64,${attachment.data_base64}`
}

function safeFilename(filename: string): string {
  return filename.replace(/[\\/\r\n\0]/g, '_').slice(0, 160) || 'attachment'
}
</script>

<style scoped>
.mms-attachments { display: grid; gap: 10px; margin: 14px 0; }
.mms-attachment { min-width: 0; overflow-wrap: anywhere; }
.mms-image { display: block; max-width: 100%; max-height: 420px; object-fit: contain; border-radius: 8px; }
</style>
