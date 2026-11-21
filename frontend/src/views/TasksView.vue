<template>
  <div class="page">
    <el-tabs v-model="zone" @tab-change="load">
      <el-tab-pane label="已逾期" name="overdue" />
      <el-tab-pane label="今日待办" name="today" />
      <el-tab-pane label="即将到期" name="upcoming" />
    </el-tabs>

    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="member_name" label="会员" min-width="110" />
      <el-table-column label="份额" min-width="90">
        <template #default="{ row }">{{ shareLabel(row.share_type) }}</template>
      </el-table-column>
      <el-table-column prop="remain_times" label="剩余次数" width="90" />
      <el-table-column label="计划时间" width="160">
        <template #default="{ row }">{{ fmt(row.plan_time) }}</template>
      </el-table-column>
      <el-table-column label="到期时间" width="160">
        <template #default="{ row }">{{ fmt(row.expire_deadline) }}</template>
      </el-table-column>
      <el-table-column prop="content_preview" label="文案预览" min-width="220" show-overflow-tooltip />
      <el-table-column label="操作" width="270" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button size="small" :type="row.copied ? 'success' : 'primary'" @click="copyContent(row)">
            {{ row.copied ? '已复制' : '复制文案' }}
          </el-button>
          <el-button size="small" type="success" @click="openComplete(row)">完成</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next, total"
      class="pager"
      @current-change="load"
    />

    <!-- 任务详情抽屉 -->
    <el-drawer v-model="detailVisible" title="任务详情" size="45%">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small" class="detail-block">
          <el-descriptions-item label="会员">
            {{ detail.member?.nickname || detail.member?.real_name || '-' }}
            （{{ detail.member?.ext_member_id }}）
          </el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusLabel(detail.task.status) }}</el-descriptions-item>
          <el-descriptions-item label="商品">{{ detail.share?.good_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="剩余次数">
            {{ detail.share?.remain_times }} / {{ detail.share?.total_cnt }}
          </el-descriptions-item>
          <el-descriptions-item label="配送周期">{{ detail.share?.cycle_desc || '-' }}</el-descriptions-item>
          <el-descriptions-item label="配送期间">
            {{ (detail.share?.start_ship_date || '').slice(0, 10) }} ~
            {{ (detail.share?.end_ship_date || '').slice(0, 10) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="content-box">
          <div class="content-text">{{ detail.content || '（模板渲染内容为空）' }}</div>
          <el-button type="primary" size="small" @click="copyDetail">复制文案（留痕）</el-button>
        </div>

        <h4>触达历史（本会员最近 20 次）</h4>
        <el-table :data="detail.touch_history" size="small" max-height="220">
          <el-table-column label="结果" width="100">
            <template #default="{ row }">{{ resultLabel(row.result) }}</template>
          </el-table-column>
          <el-table-column label="完成时间" min-width="160">
            <template #default="{ row }">{{ fmt(row.completed_at) }}</template>
          </el-table-column>
        </el-table>

        <div v-if="detail.task.status === 'pending'" class="detail-actions">
          <el-button type="success" @click="openCompleteFromDetail">标记完成</el-button>
          <el-button @click="openReschedule">改期</el-button>
          <el-button type="danger" plain @click="openCancel">取消</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 完成回填弹窗 -->
    <el-dialog v-model="completeVisible" title="标记完成 + 结果回填" width="460px">
      <el-form label-width="80px">
        <el-form-item label="结果" required>
          <el-radio-group v-model="completeForm.result">
            <el-radio v-for="(label, key) in RESULT_LABELS" :key="key" :value="key">{{ label }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="completeForm.remark" type="textarea" :rows="3"
                    :placeholder="completeForm.result === 'other' ? '选「其他」时必填' : '可选填'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="completeVisible = false">取消</el-button>
        <el-button type="success" :loading="saving" @click="submitComplete">确认完成</el-button>
      </template>
    </el-dialog>

    <!-- 改期弹窗 -->
    <el-dialog v-model="rescheduleVisible" title="任务改期" width="420px">
      <el-date-picker v-model="rescheduleForm.time" type="datetime"
                      placeholder="新的计划时间" format="YYYY-MM-DD HH:mm" />
      <el-input v-model="rescheduleForm.reason" placeholder="改期原因（必填）" class="gap-top" />
      <template #footer>
        <el-button @click="rescheduleVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReschedule">确认</el-button>
      </template>
    </el-dialog>

    <!-- 取消弹窗 -->
    <el-dialog v-model="cancelVisible" title="取消任务" width="420px">
      <el-input v-model="cancelForm.reason" placeholder="取消原因（必填）" />
      <template #footer>
        <el-button @click="cancelVisible = false">取消</el-button>
        <el-button type="danger" :loading="saving" @click="submitCancel">确认取消任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  csTasks, csTaskDetail, csTaskCopy, csTaskComplete, csTaskCancel, csTaskReschedule,
  RESULT_LABELS, type TaskItem, type TaskDetail, type TaskZone, type TaskResult,
} from '../api/tasks'
import { SHARE_TYPE_LABELS } from '../api/members'

const zone = ref<TaskZone>('today')
const items = ref<TaskItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const saving = ref(false)

const detailVisible = ref(false)
const detail = ref<TaskDetail | null>(null)

const completeVisible = ref(false)
const completeForm = ref<{ id: number; result: TaskResult; remark: string }>(
  { id: 0, result: 'renewed', remark: '' })
const rescheduleVisible = ref(false)
const rescheduleForm = ref<{ id: number; time: string; reason: string }>({ id: 0, time: '', reason: '' })
const cancelVisible = ref(false)
const cancelForm = ref<{ id: number; reason: string }>({ id: 0, reason: '' })

function shareLabel(t?: string | null) {
  return t ? SHARE_TYPE_LABELS[t] || t : '-'
}
function fmt(s?: string | null) {
  return s ? s.replace('T', ' ').slice(0, 16) : '-'
}
function statusLabel(s: string) {
  return { pending: '待处理', done: '已完成', cancelled: '已取消', expired: '已过期' }[s] || s
}
function resultLabel(r: string) {
  return (RESULT_LABELS as Record<string, string>)[r] || r
}

async function load() {
  loading.value = true
  try {
    const res = await csTasks(zone.value, page.value, pageSize)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function openDetail(row: TaskItem) {
  detail.value = await csTaskDetail(row.id)
  detailVisible.value = true
}

async function copyContent(row: TaskItem) {
  const d = await csTaskDetail(row.id)
  await navigator.clipboard.writeText(d.content)
  await csTaskCopy(row.id)
  row.copied = true
  ElMessage.success('文案已复制，系统已留痕')
}

async function copyDetail() {
  if (!detail.value) return
  await navigator.clipboard.writeText(detail.value.content)
  await csTaskCopy(detail.value.task.id)
  ElMessage.success('文案已复制，系统已留痕')
}

function openComplete(row: TaskItem) {
  completeForm.value = { id: row.id, result: 'renewed', remark: '' }
  completeVisible.value = true
}
function openCompleteFromDetail() {
  if (detail.value) openComplete({ id: detail.value.task.id } as TaskItem)
}

async function submitComplete() {
  const f = completeForm.value
  if (f.result === 'other' && !f.remark.trim()) {
    ElMessage.warning('选「其他」时备注必填')
    return
  }
  saving.value = true
  try {
    await csTaskComplete(f.id, f.result, f.remark)
    ElMessage.success('任务已完成')
    completeVisible.value = false
    detailVisible.value = false
    await load()
  } catch (e: unknown) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

function openReschedule() {
  rescheduleForm.value = { id: detail.value?.task.id || 0, time: '', reason: '' }
  rescheduleVisible.value = true
}
async function submitReschedule() {
  const f = rescheduleForm.value
  if (!f.time || !f.reason.trim()) {
    ElMessage.warning('请填写新的计划时间与原因')
    return
  }
  saving.value = true
  try {
    await csTaskReschedule(f.id, new Date(f.time).toISOString(), f.reason)
    ElMessage.success('已改期')
    rescheduleVisible.value = false
    detailVisible.value = false
    await load()
  } catch (e: unknown) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

function openCancel() {
  cancelForm.value = { id: detail.value?.task.id || 0, reason: '' }
  cancelVisible.value = true
}
async function submitCancel() {
  if (!cancelForm.value.reason.trim()) {
    ElMessage.warning('取消原因必填')
    return
  }
  saving.value = true
  try {
    await csTaskCancel(cancelForm.value.id, cancelForm.value.reason)
    ElMessage.success('任务已取消')
    cancelVisible.value = false
    detailVisible.value = false
    await load()
  } catch (e: unknown) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

function errorMessage(e: unknown): string {
  const resp = (e as { response?: { data?: { detail?: string } } })?.response?.data
  return resp?.detail || '操作失败'
}

onMounted(load)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.pager { justify-content: flex-end; }
.content-box {
  margin: 14px 0; padding: 14px; background: #f0f9eb;
  border: 1px solid #e1f3d8; border-radius: 8px;
  display: flex; flex-direction: column; gap: 10px;
}
.content-text { white-space: pre-wrap; line-height: 1.7; font-size: 14px; }
.detail-block { margin-bottom: 14px; }
.detail-actions { margin-top: 16px; }
.gap-top { margin-top: 10px; display: block; }
h4 { margin: 8px 0; color: #606266; }
</style>
