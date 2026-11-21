<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="metric">
            <div class="num">{{ summary?.should_contact ?? '-' }}</div>
            <div class="label">今日应联系</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="metric">
            <div class="num done">{{ summary?.contacted ?? '-' }}</div>
            <div class="label">已联系</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="metric">
            <div class="num overdue">{{ summary?.overdue ?? '-' }}</div>
            <div class="label">逾期未处理</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="gap">
      <template #header>今日结果分布</template>
      <el-table v-if="rows.length" :data="rows" size="small">
        <el-table-column label="结果" min-width="120">
          <template #default="{ row }">{{ resultLabel(row.result) }}</template>
        </el-table-column>
        <el-table-column label="数量" width="100" prop="count" />
        <el-table-column label="占比" min-width="220">
          <template #default="{ row }">
            <el-progress :percentage="row.pct" :stroke-width="14" />
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="今天还没有已完成的任务" :image-size="80" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { csSummary, RESULT_LABELS, type CsSummary } from '../api/tasks'

const summary = ref<CsSummary | null>(null)

const rows = computed(() => {
  const dist = summary.value?.result_distribution || {}
  const totalDone = Object.values(dist).map(Number).reduce((a, b) => a + b, 0) || 1
  return Object.entries(dist).map(([result, count]) => ({
    result,
    count: Number(count),
    pct: Math.round((Number(count) / totalDone) * 100),
  }))
})

function resultLabel(r: string) {
  return (RESULT_LABELS as Record<string, string>)[r] || r
}

onMounted(async () => {
  summary.value = await csSummary()
})
</script>

<style scoped>
.page { padding: 4px; }
.metric { text-align: center; padding: 12px 0; }
.num { font-size: 40px; font-weight: 700; color: #303133; }
.num.done { color: #67c23a; }
.num.overdue { color: #f56c6c; }
.label { color: #909399; margin-top: 4px; }
.gap { margin-top: 16px; }
</style>
