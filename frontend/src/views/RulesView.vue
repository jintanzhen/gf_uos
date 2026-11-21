<template>
  <div class="page">
    <div class="toolbar">
      <el-input v-model="search" placeholder="搜索规则名称" clearable class="search"
                @keyup.enter="load" @clear="load" />
      <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="load">
        <el-option label="启用中" value="enabled" />
        <el-option label="已停用" value="disabled" />
      </el-select>
      <el-button type="primary" @click="openCreate">新建规则</el-button>
    </div>

    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="规则名称" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="触发时间" width="100">
        <template #default="{ row }">{{ row.exec_time }}<span class="dim"> / {{ row.freq === 'weekly' ? '每周' : '每日' }}</span></template>
      </el-table-column>
      <el-table-column label="计划时间" width="90" prop="plan_time" />
      <el-table-column label="频控" width="90">
        <template #default="{ row }">{{ row.freq_m_times }}次/{{ row.freq_n_days }}天</template>
      </el-table-column>
      <el-table-column label="对照组" width="90">
        <template #default="{ row }">{{ row.experiment_enabled ? `${row.experiment_ratio}%` : '关闭' }}</template>
      </el-table-column>
      <el-table-column label="归因窗口" width="90">
        <template #default="{ row }">{{ row.attribution_days }}天</template>
      </el-table-column>
      <el-table-column label="操作" width="330" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openPreview(row)">命中预览</el-button>
          <el-button size="small" type="warning" plain :loading="scanningId === row.id" @click="doRunScan(row)">手动扫描</el-button>
          <el-button size="small" @click="openLogs(row)">扫描日志</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => onMore(cmd, row)">
            <el-button size="small">更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="toggle">{{ row.status === 'enabled' ? '停用' : '启用' }}</el-dropdown-item>
                <el-dropdown-item command="duplicate">复制规则</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑 -->
    <RuleEditor v-model="editorVisible" :rule="editingRule" @saved="load" />

    <!-- 命中预览 -->
    <el-dialog v-model="previewVisible" title="命中预览（不落库）" width="560px">
      <template v-if="preview">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="命中份额">{{ preview.hit_count }}</el-descriptions-item>
          <el-descriptions-item label="命中会员">{{ preview.member_count }}</el-descriptions-item>
          <el-descriptions-item label="实验组">{{ preview.exp_count }}</el-descriptions-item>
          <el-descriptions-item label="对照组">{{ preview.ctrl_count }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="preview.min_sample_warning" type="warning" show-icon class="gap"
                  title="实验组样本低于 30，统计效力不足（PRD 5.4.1）" />
        <h4>样本（前 10 条）</h4>
        <el-table :data="preview.sample" size="small" max-height="200">
          <el-table-column prop="member_id" label="会员内部 ID" />
          <el-table-column prop="share_detail_id" label="份额明细 ID" />
        </el-table>
      </template>
    </el-dialog>

    <!-- 扫描日志 -->
    <el-dialog v-model="logsVisible" title="扫描执行日志（F3-06）" width="880px">
      <el-table v-if="logs.length" :data="logs" size="small" max-height="420">
        <el-table-column label="扫描时间" width="160">
          <template #default="{ row }">{{ fmt(row.scan_at) }}</template>
        </el-table-column>
        <el-table-column prop="hit_count" label="命中" width="60" />
        <el-table-column prop="exp_generated" label="生成" width="60" />
        <el-table-column prop="ctrl_skipped" label="对照组" width="70" />
        <el-table-column prop="freq_skipped" label="频控" width="60" />
        <el-table-column prop="blacklist_skipped" label="黑名单" width="70" />
        <el-table-column prop="dedup_skipped" label="去重" width="60" />
        <el-table-column prop="conflict_skipped" label="互斥" width="60" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="80" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ok' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error" label="错误" min-width="120" show-overflow-tooltip />
      </el-table>
      <el-empty v-else description="还没有扫描记录" :image-size="80" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listRules, toggleRule, duplicateRule, deleteRule, previewRule, runScan, scanLogs,
  type Rule, type PreviewResult, type ScanLog,
} from '../api/rules'
import RuleEditor from './RuleEditor.vue'

const search = ref('')
const statusFilter = ref('')
const items = ref<Rule[]>([])
const loading = ref(false)

const editorVisible = ref(false)
const editingRule = ref<Rule | null>(null)

const previewVisible = ref(false)
const preview = ref<PreviewResult | null>(null)
const logsVisible = ref(false)
const logs = ref<ScanLog[]>([])
const scanningId = ref<number | null>(null)

function fmt(s: string) {
  return s ? s.replace('T', ' ').slice(0, 16) : '-'
}

async function load() {
  loading.value = true
  try {
    const res = await listRules({
      search: search.value || undefined,
      status: statusFilter.value || undefined,
    })
    items.value = res.items
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingRule.value = null
  editorVisible.value = true
}
function openEdit(row: Rule) {
  editingRule.value = row
  editorVisible.value = true
}

async function openPreview(row: Rule) {
  preview.value = await previewRule(row.id)
  previewVisible.value = true
}

async function doRunScan(row: Rule) {
  scanningId.value = row.id
  try {
    const stats = await runScan(row.id)
    ElMessage.success(
      `扫描完成：命中 ${stats.hit_count}，生成 ${stats.exp_generated}，` +
      `对照组跳过 ${stats.ctrl_skipped}，互斥 ${stats.conflict_skipped}`,
    )
    await load()
  } catch (e: unknown) {
    ElMessage.error(errorMessage(e))
  } finally {
    scanningId.value = null
  }
}

async function openLogs(row: Rule) {
  logs.value = await scanLogs(row.id)
  logsVisible.value = true
}

async function onMore(cmd: string, row: Rule) {
  try {
    if (cmd === 'toggle') {
      const updated = await toggleRule(row.id)
      ElMessage.success(updated.status === 'enabled' ? '规则已启用' : '规则已停用')
    } else if (cmd === 'duplicate') {
      await duplicateRule(row.id)
      ElMessage.success('已复制为「副本」并停用')
    } else if (cmd === 'delete') {
      await ElMessageBox.confirm('删除规则？已生成的任务保留不受影响（BR-01）。', '确认删除', { type: 'warning' })
      await deleteRule(row.id)
      ElMessage.success('已删除')
    }
    await load()
  } catch (e: unknown) {
    if ((e as { message?: string })?.message !== 'cancel') ElMessage.error(errorMessage(e))
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
.toolbar { display: flex; gap: 10px; }
.search { max-width: 280px; }
.dim { color: #909399; font-size: 12px; }
.gap { margin-top: 12px; }
h4 { margin: 10px 0 6px; color: #606266; }
</style>
