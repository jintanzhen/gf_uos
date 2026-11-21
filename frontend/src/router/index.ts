import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('../views/layout/WorkbenchLayout.vue'),
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '工作台' } },
        { path: 'tasks', name: 'tasks', component: () => import('../views/TasksView.vue'), meta: { title: '今日待办', roles: ['cs'] } },
        { path: 'members', name: 'members', component: () => import('../views/MembersView.vue'), meta: { title: '会员中心' } },
        { path: 'summary', name: 'summary', component: () => import('../views/SummaryView.vue'), meta: { title: '今日小结', roles: ['cs'] } },
        { path: 'rules', name: 'rules', component: () => import('../views/RulesView.vue'), meta: { title: '规则管理', roles: ['ops', 'admin'] } },
        { path: 'reports', name: 'reports', component: () => import('../views/ReportsView.vue'), meta: { title: '效果分析', roles: ['ops', 'admin'] } },
        { path: 'pool', name: 'pool', component: () => import('../views/PoolView.vue'), meta: { title: '公共池/黑名单', roles: ['ops', 'admin'] } },
        { path: 'system', name: 'system', component: () => import('../views/SystemView.vue'), meta: { title: '系统管理', roles: ['admin'] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

// 路由守卫：未登录跳登录页；无权限路由按角色重定向（BR-12 前端侧配合，服务端仍为准）
router.beforeEach((to) => {
  const store = useAuthStore()
  if (to.meta.public) {
    return store.isLoggedIn ? { path: '/dashboard' } : true
  }
  if (!store.isLoggedIn) return { path: '/login' }
  const roles = to.meta.roles as string[] | undefined
  if (roles && (!store.role || !roles.includes(store.role))) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
