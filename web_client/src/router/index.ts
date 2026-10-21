import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('../layout/MainLayout.vue'),
      children: [
        { path: '', redirect: '/messages' },
        { path: 'messages', name: 'messages', component: () => import('../views/MessagesView.vue') },
        { path: 'quarantine', name: 'quarantine', component: () => import('../views/QuarantineView.vue') },
        { path: 'rules', name: 'rules', component: () => import('../views/RulesView.vue') },
        { path: 'devices', name: 'devices', component: () => import('../views/DevicesView.vue') },
        { path: 'monitor', name: 'monitor', component: () => import('../views/MonitorView.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/messages' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  const authed = auth.paired || await auth.restore()
  if (to.path === '/login') {
    return authed ? '/messages' : true
  }
  if (!authed) {
    return '/login'
  }
  return true
})

export default router
