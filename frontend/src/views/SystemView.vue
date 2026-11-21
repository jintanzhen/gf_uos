<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane label="人员管理" name="operators" />
      <el-tab-pane label="数据同步" name="sync" />
    </el-tabs>

    <!-- 人员管理（方案 B） -->
    <el-card v-if="tab === 'operators'" shadow="never">
      <template #header>
        <div class="header-row">
          <span>客服账号（登录名=姓名，初始密码由超管发放；停用即触发 BR-06 任务转公共池）</span>
          <el-button size="small" @click="loadOperators">刷新</el-button>
        </div>
      </template>
      <el-table v-loading="loadingOp" :data="operators" stripe size="small">
        <el-table-column prop="name" label="姓名（登录名）" min-width="120" />
        <el-table-column label="角色" width="90">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'ops' ? 'warning' : 'info'" size="small">
              {{ { cs: '客服', ops: '运营', admin: '超管' }[row.role as 'cs'] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="账号状态" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'left'" type="danger" size="small">已停用</el-tag>
            <el-tag v-else-if="row.account_ready" type="success" size="small">已激活</el-tag>
            <el-tag v-else type="info" size="small">未激活（不可登录）</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="binding_count" label="绑定会员数" width="110" />
        <el-table-column prop="task_count" label="任务数" width="90" />
        <el-table-column prop="phone" label="手机号" width="130" />
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openReset(row)">重置密码</el-button>
            <el-button v-if="row.status === 'active' && row.role !== 'admin'" size="small" type="danger" plain
                       @click="doDisable(row)">停用</el-button>
            <el-button v-else-if="row.status === 'left'" size="small" type="success" plain
                       @click="doEnable(row)">启用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 数据同步 -->
    <el-card v-if="tab === 'sync'" shadow="never">
      <template #header>
        <div class="header-row">
          <span>数据同步（每日 02:30 自动执行，BR-08 失败不阻断）</span>
          <el-button type="primary" size="small" :loading="syncing" @click="doSync">手动同步（后台执行）</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="logs" stripe size="small">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="sync_type" label="类型" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ok' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_source" label="源行数" width="110" />
        <el-table-column prop="total_local" label="本地行数" width="110" />
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">{{ fmt(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="结束时间" width="170">
          <template #default="{ row }">{{ fmt(row.finished_at) }}</template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="140" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 重置密码弹窗 -->
    <el-dialog v-model="resetVisible" :title="`重置密码：${resetTarget?.name}`" width="420px">
      <el-input v-model="newPassword" placeholder="新密码（至少 5 位）" show-password />
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="doReset">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  syncLogs, runSync, listOperators, resetPassword, setOperatorStatus,
  type SyncLog, type OperatorRow,
} from '../api/system'

const tab = ref('operators')
const logs = ref<SyncLog[]>([])
const loading = ref(false)
const syncing = ref(false)

const operators = ref<OperatorRow[]>([])
const loadingOp = ref(false)
const resetVisible = ref(false)
const resetTarget = ref<OperatorRow | null>(null)
const newPassword = ref('')
const resetting = ref(false)

function fmt(s?: string | null) {
  return s ? s.replace('T', ' ').slice(0, 19) : '-'
}

async function load() {
  loading.value = true
  try { logs.value = await syncLogs() } finally { loading.value = false }
}

async function doSync() {
  syncing.value = true
  try {
    await runSync('all')
    ElMessage.success('同步已在后台启动，稍后刷新查看结果')
    setTimeout(load, 3000)
  } finally {
    syncing.value = false
  }
}

async function loadOperators() {
  loadingOp.value = true
  try { operators.value = await listOperators() } finally { loadingOp.value = false }
}

function openReset(row: OperatorRow) {
  resetTarget.value = row
  newPassword.value = ''
  resetVisible.value = true
}

async function doReset() {
  if (!resetTarget.value || newPassword.value.length < 5) {
    ElMessage.warning('密码至少 5 位')
    return
  }
  resetting.value = true
  try {
    const res = await resetPassword(resetTarget.value.id, newPassword.value)
    ElMessage.success(res.activated
      ? `账号 ${resetTarget.value.name} 已激活，请将新密码告知本人`
      : `已重置 ${resetTarget.value.name} 的密码`)
    resetVisible.value = false
    await loadOperators()
  } finally {
    resetting.value = false
  }
}

async function doDisable(row: OperatorRow) {
  try {
    await ElMessageBox.confirm(
      `停用 ${row.name}？其名下在途任务将于下一分钟自动转入公共池（BR-06），登录立即失效。`,
      '确认停用', { type: 'warning' })
  } catch { return }
  await setOperatorStatus(row.id, 'left')
  ElMessage.success(`已停用 ${row.name}`)
  await loadOperators()
}

async function doEnable(row: OperatorRow) {
  await setOperatorStatus(row.id, 'active')
  ElMessage.success(`已启用 ${row.name}`)
  await loadOperators()
}

onMounted(() => { loadOperators(); load() })
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.header-row { display: flex; justify-content: space-between; align-items: center; }
</style>
