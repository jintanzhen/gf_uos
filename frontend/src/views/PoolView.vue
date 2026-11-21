<template>
  <div class="page">
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="公共池待办（认领）" name="pool" />
      <el-tab-pane label="黑名单管理" name="blacklist" />
    </el-tabs>

    <!-- 公共池 -->
    <template v-if="tab === 'pool'">
      <el-alert type="info" show-icon :closable="false" class="gap"
                title="无归属客服会员的任务进入公共池；认领后任务归属认领人并留痕（F4-12/R4）" />
      <el-table v-loading="loading" :data="poolItems" stripe>
        <el-table-column prop="id" label="任务 ID" width="90" />
        <el-table-column prop="member_id" label="会员（内部 ID）" width="130" />
        <el-table-column prop="rule_id" label="规则 ID" width="90" />
        <el-table-column label="计划时间" width="160">
          <template #default="{ row }">{{ fmt(row.plan_time) }}</template>
        </el-table-column>
        <el-table-column label="到期时间" width="160">
          <template #default="{ row }">{{ fmt(row.expire_deadline) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="doClaim(row)">认领</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="20" :total="total"
                     layout="prev, pager, next, total" class="pager" @current-change="loadPool" />
    </template>

    <!-- 黑名单 -->
    <template v-if="tab === 'blacklist'">
      <el-alert type="info" show-icon :closable="false" class="gap"
                title="加入黑名单的会员不参与规则扫描；其全部在途任务自动取消（BR-02）。不删除历史数据。" />
      <div class="toolbar">
        <el-input v-model="blForm.member_id" placeholder="会员内部 ID" style="width: 160px" />
        <el-date-picker v-model="blForm.until" type="date" value-format="YYYY-MM-DD"
                        placeholder="解除日期（空=永久）" />
        <el-input v-model="blForm.reason" placeholder="原因（如：拒绝触达）" style="width: 220px" />
        <el-button type="danger" @click="doAddBlacklist">加入黑名单</el-button>
      </div>
      <el-table v-loading="loading" :data="blacklist" stripe>
        <el-table-column prop="id" label="记录 ID" width="90" />
        <el-table-column prop="member_id" label="会员（内部 ID）" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'danger' : 'info'" size="small">
              {{ row.is_active ? '生效中' : '已解除' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="解除日期" width="120">
          <template #default="{ row }">{{ row.until_date || '永久' }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="160" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button v-if="row.is_active" size="small" @click="doUnblock(row)">解除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { poolTasks, claimTask, listBlacklist, addBlacklist, unblock,
         type PoolTask, type BlacklistRow } from '../api/pool'

const tab = ref('pool')
const poolItems = ref<PoolTask[]>([])
const blacklist = ref<BlacklistRow[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const blForm = ref({ member_id: '', until: '', reason: '' })

function fmt(s?: string | null) {
  return s ? s.replace('T', ' ').slice(0, 16) : '-'
}

async function loadPool() {
  loading.value = true
  try {
    const res = await poolTasks(page.value)
    poolItems.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadBlacklist() {
  loading.value = true
  try { blacklist.value = await listBlacklist() } finally { loading.value = false }
}

async function load() {
  if (tab.value === 'pool') await loadPool()
  else await loadBlacklist()
}

async function doClaim(row: PoolTask) {
  try {
    await ElMessageBox.confirm(`认领任务 #${row.id}？认领后任务归属您。`, '确认认领', { type: 'info' })
  } catch { return }
  await claimTask(row.id)
  ElMessage.success('认领成功，可在今日待办中处理')
  await loadPool()
}

async function doAddBlacklist() {
  const mid = Number(blForm.value.member_id)
  if (!mid) { ElMessage.warning('请填写会员内部 ID'); return }
  try {
    await ElMessageBox.confirm('加入黑名单将取消该会员全部在途任务，确认？', '确认', { type: 'warning' })
  } catch { return }
  const res = await addBlacklist({
    member_id: mid,
    until_date: blForm.value.until || undefined,
    reason: blForm.value.reason || undefined,
  })
  ElMessage.success(`已加入黑名单，取消在途任务 ${res.cancelled_tasks} 条`)
  blForm.value = { member_id: '', until: '', reason: '' }
  await loadBlacklist()
}

async function doUnblock(row: BlacklistRow) {
  await unblock(row.id)
  ElMessage.success('已解除黑名单（历史保留）')
  await loadBlacklist()
}

onMounted(loadPool)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 10px; }
.pager { justify-content: flex-end; }
.gap { margin-bottom: 10px; }
</style>
