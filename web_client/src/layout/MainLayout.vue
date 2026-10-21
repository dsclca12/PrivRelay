<template>
  <el-container class="app-layout">
    <el-aside :width="collapsed ? '64px' : '220px'" class="app-sidebar">
      <div class="brand">
        <div class="brand-badge">
          <el-icon><Connection /></el-icon>
        </div>
        <div v-show="!collapsed" class="brand-text">
          <span class="brand-name">PrivRelay</span>
          <span class="brand-sub">短信管理控制台</span>
        </div>
      </div>

      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
        :collapse-transition="false"
      >
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path" :aria-label="item.title" :title="item.title">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>

      <div v-show="!collapsed" class="sidebar-footer">
        <div class="device-line">
          <el-icon><Cellphone /></el-icon>
          <span>{{ auth.deviceName || '本浏览器' }}</span>
        </div>
        <div class="device-line">
          <el-icon><Key /></el-icon>
          <el-tooltip :content="auth.deviceId || '（未记录设备 ID）'" placement="top">
            <span>{{ auth.deviceId ? shortId(auth.deviceId) : '—' }}</span>
          </el-tooltip>
        </div>
        <el-button size="small" text style="justify-content: flex-start" @click="onLogout">
          <el-icon style="margin-right: 4px"><SwitchButton /></el-icon>
          退出登录
        </el-button>
      </div>
    </el-aside>

    <el-container direction="vertical">
      <el-header class="app-header" height="56px">
        <span class="page-title">{{ pageTitle }}</span>

        <el-tag :type="statusMeta.type" size="small" effect="light">
          <span class="tag-content">
            <el-icon v-if="syncStatus === 'live'"><VideoCameraFilled /></el-icon>
            <el-icon v-else><Clock /></el-icon>
            {{ statusMeta.text }}
          </span>
        </el-tag>
        <span class="sync-line">
          最近同步 {{ lastSyncAt ? formatClock(lastSyncAt) : '—' }}
        </span>

        <span class="header-spacer" />

        <el-button size="small" aria-label="刷新" :loading="messages.loading" @click="() => refresh()">
          <el-icon style="margin-right: 4px"><Refresh /></el-icon>
          <span class="refresh-label">刷新</span>
        </el-button>
        <el-tooltip :content="themeDark ? '切换到浅色模式' : '切换到深色模式'" placement="bottom">
          <el-button size="small" :aria-label="themeDark ? '切换到浅色模式' : '切换到深色模式'" circle @click="toggleTheme">
            <el-icon><Sunny v-if="!themeDark" /><Moon v-else /></el-icon>
          </el-button>
        </el-tooltip>
        <el-popconfirm title="退出当前浏览器会话？" confirm-button-text="退出" cancel-button-text="取消" @confirm="onLogout">
          <template #reference>
            <el-button size="small" circle aria-label="退出登录">
              <el-icon><SwitchButton /></el-icon>
            </el-button>
          </template>
        </el-popconfirm>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useSync } from '../composables/useSync'
import { useAuthStore } from '../stores/auth'
import { useMessagesStore } from '../stores/messages'
import { formatClock, shortId } from '../utils/format'

const route = useRoute()
const auth = useAuthStore()
const messages = useMessagesStore()
const { status: syncStatus, lastSyncAt, start, stop, refresh } = useSync()

const menus = [
  { path: '/messages', title: '消息中心', icon: 'ChatDotRound' },
  { path: '/quarantine', title: '拦截中心', icon: 'Filter' },
  { path: '/devices', title: '设备中心', icon: 'Cellphone' },
  { path: '/rules', title: '规则中心', icon: 'SetUp' },
  { path: '/feedback', title: '纠错审核', icon: 'EditPen' },
  { path: '/monitor', title: '运行监控', icon: 'DataAnalysis' },
] as const

const pageTitle = computed(
  () => menus.find((item) => route.path.startsWith(item.path))?.title ?? '消息中心',
)

const statusMeta = computed<{ type: 'success' | 'warning' | 'info'; text: string }>(() => {
  switch (syncStatus.value) {
    case 'live':
      return { type: 'success', text: '实时推送' }
    case 'connecting':
      return { type: 'info', text: '连接中…' }
    case 'polling':
      return { type: 'warning', text: '轮询同步' }
    default:
      return { type: 'info', text: '同步已停止' }
  }
})

/* 主题 */
const themeDark = ref(localStorage.getItem('privrelay.theme') === 'dark')

function applyTheme(): void {
  document.documentElement.classList.toggle('dark', themeDark.value)
}

function toggleTheme(): void {
  themeDark.value = !themeDark.value
  localStorage.setItem('privrelay.theme', themeDark.value ? 'dark' : 'light')
  applyTheme()
}

/* 响应式侧栏 */
const collapsed = ref(window.innerWidth < 900)

function onResize(): void {
  collapsed.value = window.innerWidth < 900
}

function onLogout(): void {
  void auth.logout()
}

onMounted(() => {
  applyTheme()
  window.addEventListener('resize', onResize)
  start()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  stop()
})
</script>
