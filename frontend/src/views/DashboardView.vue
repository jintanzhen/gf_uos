<template>
  <div class="page">
    <template v-if="isCs">
      <el-row :gutter="16">
        <el-col :span="8">
          <el-card shadow="hover" class="clickable" @click="router.push('/tasks')">
            <div class="metric">
              <div class="num">{{ summary?.should_contact ?? '-' }}</div>
              <div class="label">今日应联系</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover" class="clickable" @click="router.push('/summary')">
            <div class="metric">
              <div class="num done">{{ summary?.contacted ?? '-' }}</div>
              <div class="label">已联系</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover" class="clickable" @click="router.push('/tasks')">
            <div class="metric">
              <div class="num overdue">{{ summary?.overdue ?? '-' }}</div>
              <div class="label">逾期未处理</div>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-card shadow="never" class="gap">
        <template #header>快捷入口</template>
        <el-space wrap>
          <el-button type="primary" @click="router.push('/tasks')">去今日待办</el-button>
          <el-button @click="router.push('/members')">查我的会员</el-button>
          <el-button @click="router.push('/summary')">今日小结</el-button>
        </el-space>
      </el-card>
    </template>

    <template v-else>
      <el-row :gutter="16">
        <el-col :span="6">
          <el-card shadow="hover" class="clickable" @click="router.push('/reports')">
            <div class="metric">
              <div class="num">{{ overview?.generated ?? '-' }}</div>
              <div class="label">任务总量</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="clickable" @click="router.push('/reports')">
            <div class="metric">
              <div class="num done">{{ overview?.done ?? '-' }}</div>
              <div class="label">已完成</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="clickable" @click="router.push('/pool')">
            <div class="metric">
              <div class="num overdue">{{ overview?.overdue ?? '-' }}</div>
              <div class="label">逾期未处理</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="hover" class="clickable" @click="router.push('/reports')">
            <div class="metric">
              <div class="num">{{ rateText }}</div>
              <div class="label">完成率</div>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-card shadow="never" class="gap">
        <template #header>快捷入口</template>
        <el-space wrap>
          <el-button type="primary" @click="router.push('/rules')">规则管理</el-button>
          <el-button @click="router.push('/members')">会员检索</el-button>
          <el-button @click="router.push('/pool')">公共池 / 黑名单</el-button>
          <el-button @click="router.push('/reports')">效果分析</el-button>
          <el-button v-if="role === 'admin'" @click="router.push('/system')">系统管理</el-button>
        </el-space>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { csSummary, type CsSummary } from '../api/tasks'
import { overview as fetchOverview, type Overview } from '../api/reports'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const store = useAuthStore()
const isCs = computed(() => store.role === 'cs')
const role = computed(() => store.role)

const summary = ref<CsSummary | null>(null)
const overview = ref<Overview | null>(null)
const rateText = computed(() => {
  const v = overview.value?.completion_rate
  return v === null || v === undefined ? '-' : `${(v * 100).toFixed(1)}%`
})

onMounted(async () => {
  if (isCs.value) {
    summary.value = await csSummary().catch(() => null)
  } else {
    overview.value = await fetchOverview().catch(() => null)
  }
})
</script>

<style scoped>
.metric { text-align: center; padding: 12px 0; }
.num { font-size: 40px; font-weight: 700; color: #303133; }
.num.done { color: #67c23a; }
.num.overdue { color: #f56c6c; }
.label { color: #909399; margin-top: 4px; }
.clickable { cursor: pointer; transition: transform 0.15s ease; }
.clickable:hover { transform: translateY(-2px); }
.gap { margin-top: 16px; }
</style>
