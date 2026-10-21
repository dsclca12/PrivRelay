<template>
  <el-card shadow="never" style="margin-bottom: 14px" v-loading="loading">
    <template #header><strong>AI / LLM 自动分类</strong></template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button v-if="error" @click="load">重新加载</el-button>
    <el-form v-else label-position="top">
      <el-form-item label="分类方式">
        <el-select v-model="form.mode" style="width: 100%">
          <el-option value="disabled" label="关闭 LLM，仅使用现有轻量分类器" />
          <el-option value="fallback" label="轻量模型失败、不确定或需复核时交给 LLM" />
          <el-option value="primary" label="直接使用 LLM 自动分类" />
        </el-select>
      </el-form-item>
      <el-form-item label="OpenAI 兼容 API 基础地址（通常以 /v1 结尾）">
        <el-input v-model="form.base_url" placeholder="填写你自己的接口地址" autocomplete="off" />
      </el-form-item>
      <el-form-item label="模型名称"><el-input v-model="form.model" placeholder="填写服务提供的模型名" /></el-form-item>
      <el-form-item :label="form.has_api_key ? 'API Key（已保存；留空保留原密钥）' : 'API Key（本地免鉴权服务可留空）'">
        <el-input v-model="key" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-checkbox v-model="clearKey">清除已保存密钥</el-checkbox>
      <el-form-item><el-switch v-model="form.allow_http" active-text="允许 HTTP（仅限可信本机或内网）" /></el-form-item>
      <el-form-item><el-switch v-model="form.auto_quarantine" active-text="允许 LLM 自动隔离营销与可疑短信" /></el-form-item>
      <el-form-item label="自动隔离最低置信度和风险分数（两者均需达到）">
        <el-slider v-model="form.threshold" :min="0.8" :max="1" :step="0.01" show-input />
      </el-form-item>
      <el-alert type="warning" :closable="false" title="启用后会把发件人和正文发送到所填接口。模型分数未经校准；验证码、交易、安全内容、白名单与人工恢复优先保护。隔离还需开启上方智能过滤或自动拦截模式。" />
      <p class="muted">默认地址、模型、密钥均为空，不会自动连接任何服务。配置对新消息和待分类消息生效；不回溯全部历史。失败时正常保留，稍后重试。</p>
      <div class="toolbar">
        <el-button type="primary" :loading="saving" @click="save">保存 AI 配置</el-button>
        <el-button :loading="testing" :disabled="saving" @click="test">测试已保存配置（合成短信）</el-button>
      </div>
      <p v-if="testResult" role="status">{{ testResult }}</p>
    </el-form>
  </el-card>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { LLMSettings } from '../api/types'
import { getLLMSettings, putLLMSettings, testLLM } from '../api/endpoints'
import { categoryMeta } from '../utils/format'
const form = ref<LLMSettings>({ mode: 'disabled', base_url: '', model: '', has_api_key: false, allow_http: false, auto_quarantine: false, threshold: 0.95 })
const loading = ref(false), saving = ref(false), testing = ref(false), key = ref(''), clearKey = ref(false), error = ref(''), testResult = ref('')
async function load() {
  loading.value = true
  try { form.value = await getLLMSettings(); error.value = '' }
  catch { error.value = 'AI 配置加载失败，请重试' }
  finally { loading.value = false }
}
async function save() {
  if (form.value.mode !== 'disabled') {
    if (!form.value.base_url.trim() || !form.value.model.trim()) { ElMessage.error('请填写接口地址和模型名称'); return }
    try { await ElMessageBox.confirm(`启用后将向 ${form.value.base_url} 发送短信发件人和正文用于分类。${form.value.auto_quarantine ? '同时允许满足条件的营销或可疑消息自动进入可恢复的拦截箱。' : ''}`, '确认 AI 处理目的地', { type: 'warning' }) }
    catch { return }
  }
  saving.value = true
  try {
    form.value = await putLLMSettings({ ...form.value, api_key: key.value, clear_api_key: clearKey.value })
    key.value = ''; clearKey.value = false; testResult.value = ''; ElMessage.success('AI 配置已保存')
  } catch { ElMessage.error('AI 配置未保存，请检查地址、HTTP 开关与连接') }
  finally { saving.value = false }
}
async function test() {
  testing.value = true
  try { const result = await testLLM(); testResult.value = `连接成功 · ${result.model_version} · ${categoryMeta(result.category).label}（合成测试，不保存为短信）` }
  catch { testResult.value = '测试失败，请检查已保存的地址、模型、密钥和模型 JSON 输出能力' }
  finally { testing.value = false }
}
onMounted(load)
</script>
