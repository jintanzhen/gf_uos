<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="aside-brand">
        <span class="logo">G</span>
        <span class="name">运营支持系统</span>
      </div>
      <el-menu
        :default-active="route.path"
        class="aside-menu"
        router
        background-color="transparent"
        text-color="#9aa8b3"
        active-text-color="#409eff"
      >
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
      <div class="aside-footer">Green-OS · M3</div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item>Green-OS</el-breadcrumb-item>
          <el-breadcrumb-item>{{ route.meta.title || '工作台' }}</el-breadcrumb-item>
        </el-breadcrumb>
        <div class="header-right">
          <el-tag :type="roleTagType" size="small" effect="dark">{{ roleLabel }}</el-tag>
          <el-dropdown @command="onCommand">
            <span class="user-name">
              {{ store.operator?.name }}
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, DataAnalysis, Odometer, Setting, User, Bell } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore, type Role } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const store = useAuthStore()

const ALL_MENUS = [
  { path: '/dashboard', title: '工作台', icon: Odometer, roles: undefined as string[] | undefined },
  { path: '/tasks', title: '今日待办', icon: Bell, roles: ['cs'] },
  { path: '/members', title: '会员中心', icon: User, roles: undefined },
  { path: '/summary', title: '今日小结', icon: Odometer, roles: ['cs'] },
  { path: '/rules', title: '规则管理', icon: Setting, roles: ['ops', 'admin'] },
  { path: '/pool', title: '公共池/黑名单', icon: User, roles: ['ops', 'admin'] },
  { path: '/reports', title: '效果分析', icon: DataAnalysis, roles: ['ops', 'admin'] },
  { path: '/system', title: '系统管理', icon: Setting, roles: ['admin'] },
]

const menus = computed(() =>
  ALL_MENUS.filter((m) => !m.roles || (store.role && m.roles.includes(store.role))),
)

const ROLE_LABELS: Record<Role, string> = { cs: '客服', ops: '运营', admin: '超管' }
const roleLabel = computed(() => ROLE_LABELS[(store.role ?? 'cs') as Role] ?? '-')
const roleTagType = computed(() =>
  store.role === 'admin' ? 'danger' : store.role === 'ops' ? 'warning' : 'success',
)

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
      .then(() => {
        store.logout()
        router.push('/login')
      })
      .catch(() => undefined)
  }
}
</script>

<style scoped>
.layout { height: 100%; }
.aside {
  display: flex;
  flex-direction: column;
  background: #1d2b35;
  transition: width 0.2s ease;
}
.aside-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 60px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.logo {
  width: 34px; height: 34px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 18px; color: #fff;
  background: linear-gradient(135deg, #409eff, #67c23a);
}
.name { color: #e6ebf0; font-size: 14px; font-weight: 600; letter-spacing: 1px; }

.aside-menu { border-right: none; flex: 1; padding-top: 8px; }
.aside-menu :deep(.el-menu-item) {
  margin: 4px 10px;
  border-radius: 8px;
  transition: background 0.15s ease;
}
.aside-menu :deep(.el-menu-item:hover) { background: rgba(255, 255, 255, 0.07); }
.aside-menu :deep(.el-menu-item.is-active) { background: rgba(64, 158, 255, 0.16); }

.aside-footer { padding: 14px 18px; font-size: 11px; color: rgba(255, 255, 255, 0.3); }

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.header-right { display: flex; align-items: center; gap: 12px; }
.user-name {
  display: flex; align-items: center; gap: 4px;
  cursor: pointer; color: #303133; font-size: 14px; outline: none;
}
.main { background: #f5f7fa; padding: 20px; }
</style>
