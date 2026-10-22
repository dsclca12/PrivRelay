<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="login-logo">
          <el-icon><Connection /></el-icon>
        </div>
        <div class="login-title">PrivRelay 控制台</div>
        <div class="login-subtitle">基于隐私保护与智能分类的跨设备短信管理系统</div>
      </div>

      <el-card shadow="never">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="设备配对" name="pair">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="配对码由服务端启动时打印，10 分钟内有效且只能使用一次。"
              style="margin-bottom: 14px"
            />
            <div style="display: flex; flex-direction: column; gap: 14px">
              <el-input
                v-model="pairingCode"
                placeholder="一次性配对码"
                clearable
                size="large"
                @keyup.enter="handlePair"
              />
              <el-input v-model="deviceName" placeholder="设备名称" size="large" maxlength="64" />
              <el-input v-model="vaultPassphrase" type="password" show-password placeholder="端到端加密口令（至少 12 个可见 ASCII 字符；授权设备需使用相同口令）" size="large" />
              <el-button
                type="primary"
                size="large"
                :loading="pairing"
                style="width: 100%"
                @click="handlePair"
              >
                生成密钥并配对本浏览器
              </el-button>
            </div>
          </el-tab-pane>

          <el-tab-pane label="访问令牌" name="token">
            <div style="display: flex; flex-direction: column; gap: 14px">
              <el-input
                v-model="tokenInput"
                type="password"
                show-password
                placeholder="访问令牌（Bearer Token）"
                size="large"
                @keyup.enter="handleToken"
              />
              <el-input
                v-model="deviceIdInput"
                placeholder="设备 ID（可选，仅用于展示）"
                size="large"
                clearable
                @keyup.enter="handleToken"
              />
              <el-button
                type="primary"
                size="large"
                :loading="entering"
                style="width: 100%"
                @click="handleToken"
              >
                进入控制台
              </el-button>
            </div>
          </el-tab-pane>
        </el-tabs>

        <ul class="privacy-notes">
          <li>· 控制台只与你自己的自托管服务端通信，不经过任何第三方云端。</li>
          <li>· 配对使用浏览器 WebCrypto 生成的 ECDSA P-256 密钥签名，令牌仅保存在本浏览器。</li>
          <li>· 短信正文端到端加密后才上传；云端不能读取、分类或搜索正文。</li>
        </ul>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { errorText, useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const activeTab = ref('pair')
const pairingCode = ref('')
const deviceName = ref('Web 控制台')
const vaultPassphrase = ref('')
const tokenInput = ref('')
const deviceIdInput = ref('')
const pairing = ref(false)
const entering = ref(false)

async function redirectNext(): Promise<void> {
  const next = typeof route.query.next === 'string' ? route.query.next : '/messages'
  await router.replace(next)
}

async function handlePair(): Promise<void> {
  if (!pairingCode.value.trim()) {
    ElMessage.warning('请输入服务端控制台输出的配对码')
    return
  }
  pairing.value = true
  try {
    await auth.pair(pairingCode.value, deviceName.value, vaultPassphrase.value)
    ElMessage.success('配对成功，本浏览器已获得访问授权')
    await redirectNext()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '配对失败，请重试')
  } finally {
    pairing.value = false
  }
}

async function handleToken(): Promise<void> {
  if (!tokenInput.value.trim()) {
    ElMessage.warning('请输入访问令牌')
    return
  }
  entering.value = true
  try {
    await auth.useToken(tokenInput.value, deviceIdInput.value)
    await redirectNext()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? errorText(error.code) : '登录失败，请重试')
  } finally {
    entering.value = false
  }
}
</script>
