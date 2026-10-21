<template>
  <div class="rules-form" v-loading="loading">
    <div class="toolbar">
      <span class="muted">规则保存后对新到达的消息立即生效，不回溯已处理的历史消息。</span>
      <span class="toolbar-spacer" />
      <el-tag v-if="dirty" type="warning" size="small" effect="light">有未保存的修改</el-tag>
      <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">
        <el-icon style="margin-right: 4px"><Check /></el-icon>
        保存规则
      </el-button>
    </div>

    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header>
        <span style="font-weight: 600">过滤模式</span>
      </template>
      <div class="mode-options">
        <div
          v-for="mode in MODES"
          :key="mode.value"
          class="mode-card"
          :class="{ active: form.mode === mode.value }"
          @click="form.mode = mode.value"
        >
          <div class="mode-name">
            <el-icon><component :is="mode.icon" /></el-icon>
            {{ mode.name }}
          </div>
          <div class="mode-desc">{{ mode.desc }}</div>
        </div>
      </div>
      <el-alert
        v-if="form.mode === 'classify'"
        type="info"
        :closable="false"
        show-icon
        title="仅分类模式下，阈值与名单仍会保存，但不会隔离任何短信。"
        style="margin-top: 12px"
      />
      <el-alert
        v-if="form.mode === 'block'"
        type="warning"
        :closable="false"
        show-icon
        title="自动拦截模式在服务端执行与智能过滤相同的隔离策略；系统级通知抑制由 Android 客户端负责。"
        style="margin-top: 12px"
      />
    </el-card>

    <el-card shadow="never" style="margin-bottom: 14px">
      <template #header>
        <span style="font-weight: 600">隔离阈值</span>
      </template>
      <el-slider
        v-model="form.threshold"
        :min="0.8"
        :max="1"
        :step="0.01"
        show-input
        :show-input-width="160"
        style="max-width: 520px"
      />
      <p class="muted" style="margin-top: 6px">
        仅当模型类别为营销 / 可疑、置信度校准通过且置信度 ≥ 阈值时才会隔离（当前
        {{ (form.threshold * 100).toFixed(0) }}%）。阈值范围 0.80 – 1.00，建议从 0.95 起步。
      </p>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <span style="font-weight: 600">白名单与黑名单</span>
      </template>
      <el-form label-position="top">
        <el-form-item label="白名单：这些发送方永远正常展示（优先于黑名单与阈值）">
          <el-input
            v-model="whitelistText"
            type="textarea"
            :rows="5"
            class="list-editor"
            placeholder="每行一个发送方号码或名称，例如：&#10;10086&#10;95588"
          />
        </el-form-item>
        <el-form-item label="黑名单：这些发送方直接进入拦截箱（验证码与交易保护规则仍优先）">
          <el-input
            v-model="blacklistText"
            type="textarea"
            :rows="5"
            class="list-editor"
            placeholder="每行一个发送方号码，例如：&#10;10690005555"
          />
        </el-form-item>
      </el-form>
      <p class="muted">
        每行一条，单条 ≤ 128 字符，各列表 ≤ 500 条。当前白名单 {{ whitelistCount }} 条、黑名单
        {{ blacklistCount }} 条。
      </p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '../api/client'
import { getRules, putRules } from '../api/endpoints'
import type { Rules } from '../api/types'
import { errorText } from '../stores/auth'

interface ModeOption {
  value: 'classify' | 'filter' | 'block'
  name: string
  desc: string
  icon: string
}

const MODES: ModeOption[] = [
  {
    value: 'classify',
    name: '模式 A · 仅分类',
    desc: '所有短信正常展示，分类标签与风险评分仅作提示，不做任何隔离。',
    icon: 'Tag',
  },
  {
    value: 'filter',
    name: '模式 B · 智能过滤',
    desc: '符合策略的营销 / 可疑短信移入独立拦截箱，正常收件箱不再展示，可随时恢复。',
    icon: 'Filter',
  },
  {
    value: 'block',
    name: '模式 C · 自动拦截',
    desc: '在智能过滤基础上启用自动隔离；通知抑制由 Android 端配合完成。',
    icon: 'Lock',
  },
]

const loading = ref(false)
const saving = ref(false)
const form = ref<Rules>({ mode: 'classify', threshold: 0.95, whitelist: [], blacklist: [] })
const whitelistText = ref('')
const blacklistText = ref('')
const originalSnapshot = ref('')

function parseList(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function snapshot(): string {
  return JSON.stringify({
    mode: form.value.mode,
    threshold: form.value.threshold,
    whitelist: whitelistText.value,
    blacklist: blacklistText.value,
  })
}

const dirty = computed(() => originalSnapshot.value !== '' && snapshot() !== originalSnapshot.value)
const whitelistCount = computed(() => parseList(whitelistText.value).length)
const blacklistCount = computed(() => parseList(blacklistText.value).length)

async function load(): Promise<void> {
  loading.value = true
  try {
    const rules = await getRules()
    form.value = {
      mode: rules.mode,
      threshold: rules.threshold,
      whitelist: [...rules.whitelist],
      blacklist: [...rules.blacklist],
    }
    whitelistText.value = rules.whitelist.join('\n')
    blacklistText.value = rules.blacklist.join('\n')
    originalSnapshot.value = snapshot()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '规则加载失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  const whitelist = parseList(whitelistText.value)
  const blacklist = parseList(blacklistText.value)

  if (whitelist.length > 500 || blacklist.length > 500) {
    ElMessage.error('单个名单最多 500 条')
    return
  }
  const tooLong = [...whitelist, ...blacklist].find((entry) => entry.length > 128)
  if (tooLong) {
    ElMessage.error(`名单条目超过 128 字符：${tooLong.slice(0, 32)}…`)
    return
  }
  if (form.value.threshold < 0.8 || form.value.threshold > 1) {
    ElMessage.error('阈值必须在 0.80 – 1.00 之间')
    return
  }

  saving.value = true
  try {
    const rules = await putRules({
      mode: form.value.mode,
      threshold: Number(form.value.threshold.toFixed(2)),
      whitelist,
      blacklist,
    })
    form.value = { ...rules }
    whitelistText.value = rules.whitelist.join('\n')
    blacklistText.value = rules.blacklist.join('\n')
    originalSnapshot.value = snapshot()
    ElMessage.success('规则已保存并对新消息生效')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '规则保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>
