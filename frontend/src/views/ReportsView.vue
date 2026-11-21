<template>
  <div class="page">
    <el-tabs v-model="tab">
      <el-tab-pane label="任务总览" name="overview" />
      <el-tab-pane label="实验效果对比" name="experiment" />
      <el-tab-pane label="规则排行榜" name="ranking" />
      <el-tab-pane label="客服绩效" name="csperf" />
    </el-tabs>

    <!-- F6-01 任务总览 -->
    <template v-if="tab === 'overview'">
      <div class="toolbar">
        <el-select v-model="ovRuleId" clearable placeholder="全部规则" style="width: 220px" @change="loadOverview">
          <el-option v-for="r in rules" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
        <el-date-picker v-model="ovRange" type="daterange" value-format="YYYY-MM-DD"
                        start-placeholder="开始日期" end-placeholder="结束日期" @change="loadOverview" />
      </div>
      <el-row :gutter="12" class="gap">
        <el-col :span="4"><el-card shadow="hover"><StatCard label="生成" :value="ov?.generated" /></el-card></el-col>
        <el-col :span="4"><el-card shadow="hover"><StatCard label="已完成" :value="ov?.done" color="#67c23a" /></el-card></el-col>
        <el-col :span="4"><el-card shadow="hover"><StatCard label="待处理" :value="ov?.pending" /></el-card></el-col>
        <el-col :span="4"><el-card shadow="hover"><StatCard label="逾期" :value="ov?.overdue" color="#f56c6c" /></el-card></el-col>
        <el-col :span="4"><el-card shadow="hover"><StatCard label="完成率" :value="pct(ov?.completion_rate)" /></el-card></el-col>
        <el-col :span="4"><el-card shadow="hover"><StatCard label="平均响应(分)" :value="mins(ov?.avg_latency_seconds)" /></el-card></el-col>
      </el-row>
      <el-row :gutter="16" class="gap">
        <el-col :span="8">
          <el-card shadow="never">
            <template #header>结果分布</template>
            <el-table v-if="distRows.length" :data="distRows" size="small">
              <el-table-column label="结果" prop="label" />
              <el-table-column label="数量" prop="count" width="80" />
            </el-table>
            <el-empty v-else description="暂无数据" :image-size="60" />
          </el-card>
        </el-col>
        <el-col :span="16">
          <el-card shadow="never">
            <template #header>按日趋势（生成 / 完成）</template>
            <el-table v-if="ov?.by_day?.length" :data="ov.by_day" size="small" max-height="300">
              <el-table-column prop="date" label="日期" width="120" />
              <el-table-column prop="generated" label="生成" width="100" />
              <el-table-column prop="done" label="完成" width="100" />
              <el-table-column label="完成率" min-width="200">
                <template #default="{ row }">
                  <el-progress :percentage="row.generated ? Math.round(row.done / row.generated * 100) : 0" />
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无数据" :image-size="60" />
          </el-card>
        </el-col>
      </el-row>
    </template>

    <!-- F6-02 实验效果对比（核心） -->
    <template v-if="tab === 'experiment'">
      <div class="toolbar">
        <el-select v-model="expRuleId" placeholder="选择规则" style="width: 280px" @change="loadExperiment">
          <el-option v-for="r in rules" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
        <el-button v-if="exp" :loading="recalcing" @click="doRecompute">历史重算（F6-05）</el-button>
      </div>
      <template v-if="exp">
        <el-alert v-if="exp.warning" type="warning" show-icon :title="exp.warning" class="gap" />
        <el-row :gutter="16" class="gap">
          <el-col :span="12">
            <el-card shadow="never">
              <template #header><b>实验组</b>（收到任务）</template>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="生成任务">{{ exp.exp.generated }}</el-descriptions-item>
                <el-descriptions-item label="已触达">{{ exp.exp.done }}</el-descriptions-item>
                <el-descriptions-item label="触达率">{{ pct(exp.exp.contact_rate) }}</el-descriptions-item>
                <el-descriptions-item label="归因续订">{{ exp.exp.renewals }}</el-descriptions-item>
                <el-descriptions-item label="续订率(按触达)">{{ pct(exp.exp.renew_rate_of_done) }}</el-descriptions-item>
                <el-descriptions-item label="续订率(按生成)">{{ pct(exp.exp.renew_rate_of_generated) }}</el-descriptions-item>
              </el-descriptions>
              <div class="signal-row">
                <el-tag v-for="(n, sig) in exp.exp.signal_distribution" :key="sig" size="small" class="gap-tag">
                  {{ signalLabel(String(sig)) }}: {{ n }}
                </el-tag>
              </div>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never">
              <template #header><b>对照组</b>（未触达，自行续订=基线）</template>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="会员数">{{ exp.ctrl.members }}</el-descriptions-item>
                <el-descriptions-item label="自行续订">{{ exp.ctrl.renewals }}</el-descriptions-item>
                <el-descriptions-item label="基线续订率">{{ pct(exp.ctrl.renew_rate) }}</el-descriptions-item>
                <el-descriptions-item label="归因窗口">{{ exp.rule.attribution_days }} 天</el-descriptions-item>
              </el-descriptions>
            </el-card>
          </el-col>
        </el-row>
        <el-card shadow="never" class="gap">
          <template #header>增量效果</template>
          <el-descriptions :column="4" border>
            <el-descriptions-item label="差值">{{ pct(exp.diff) }}</el-descriptions-item>
            <el-descriptions-item label="相对提升">{{ pct(exp.relative_lift) }}</el-descriptions-item>
            <el-descriptions-item label="p 值">{{ exp.p_value ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="结论可信">
              <el-tag :type="exp.conclusion_reliable ? 'success' : 'warning'" size="small">
                {{ exp.conclusion_reliable ? '可信' : '样本不足' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </template>
      <el-empty v-else description="选择一条规则查看实验效果" :image-size="80" class="gap" />
    </template>

    <!-- F6-06 规则排行榜 -->
    <template v-if="tab === 'ranking'">
      <el-table v-loading="loadingRank" :data="ranking" stripe size="small">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="rule_name" label="规则" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
              {{ row.status === 'enabled' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务/触达" width="110">
          <template #default="{ row }">{{ row.exp.generated }} / {{ row.exp.done }}</template>
        </el-table-column>
        <el-table-column label="实验组续订率" width="120">
          <template #default="{ row }">{{ pct(row.exp.renew_rate_of_done) }}</template>
        </el-table-column>
        <el-table-column label="对照基线" width="110">
          <template #default="{ row }">{{ pct(row.ctrl.renew_rate) }}</template>
        </el-table-column>
        <el-table-column label="差值" width="90">
          <template #default="{ row }">{{ pct(row.diff) }}</template>
        </el-table-column>
        <el-table-column label="相对提升" width="110">
          <template #default="{ row }">
            <span :style="{ color: (row.relative_lift ?? 0) > 0 ? '#67c23a' : '#f56c6c', fontWeight: 600 }">
              {{ pct(row.relative_lift) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="可信" width="90">
          <template #default="{ row }">
            <el-tag :type="row.conclusion_reliable ? 'success' : 'warning'" size="small">
              {{ row.conclusion_reliable ? '是' : '样本不足' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <!-- F6-07 客服绩效 -->
    <template v-if="tab === 'csperf'">
      <el-table v-loading="loadingPerf" :data="perf" stripe size="small">
        <el-table-column prop="cs_name" label="客服" min-width="120" />
        <el-table-column prop="generated" label="任务量" width="100" />
        <el-table-column prop="done" label="完成量" width="100" />
        <el-table-column label="完成率" width="110">
          <template #default="{ row }">{{ pct(row.completion_rate) }}</template>
        </el-table-column>
        <el-table-column label="按时完成率" width="110">
          <template #default="{ row }">{{ pct(row.on_time_rate) }}</template>
        </el-table-column>
        <el-table-column label="平均响应(分)" width="110">
          <template #default="{ row }">{{ mins(row.avg_latency_seconds) }}</template>
        </el-table-column>
        <el-table-column prop="attributed_renewals" label="归因续订数" width="110" />
      </el-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import {
  overview as fetchOverview, experiment as fetchExperiment,
  rulesRanking, csPerformance, recompute,
  SIGNAL_LABELS, RESULT_LABELS, type Overview, type Experiment, type RankRow, type CsPerf,
} from '../api/reports'
import { listRules, type Rule } from '../api/rules'

const StatCard = defineComponent({
  props: { label: String, value: { type: [String, Number], default: '-' }, color: String },
  setup(props) {
    return () => h('div', { style: 'text-align:center;padding:6px 0' }, [
      h('div', {
        style: `font-size:26px;font-weight:700;color:${props.color || '#303133'}`,
      }, String(props.value ?? '-')),
      h('div', { style: 'font-size:12px;color:#909399;margin-top:2px' }, props.label),
    ])
  },
})

const tab = ref('overview')
const rules = ref<Rule[]>([])

const ov = ref<Overview | null>(null)
const ovRuleId = ref<number | undefined>()
const ovRange = ref<[string, string] | null>(null)
const distRows = computed(() => {
  const dist = ov.value?.result_distribution || {}
  return Object.entries(dist).map(([key, count]) => ({
    label: (RESULT_LABELS as Record<string, string>)[key] || key,
    count,
  }))
})

const expRuleId = ref<number | undefined>()
const exp = ref<Experiment | null>(null)
const recalcing = ref(false)

const ranking = ref<RankRow[]>([])
const loadingRank = ref(false)
const perf = ref<CsPerf[]>([])
const loadingPerf = ref(false)

function pct(v?: number | null) {
  return v === null || v === undefined ? '-' : `${(v * 100).toFixed(1)}%`
}
function mins(sec?: number | null) {
  return sec === null || sec === undefined ? '-' : (sec / 60).toFixed(1)
}
function signalLabel(s: string) {
  return SIGNAL_LABELS[s] || s
}

async function loadOverview() {
  ov.value = await fetchOverview({
    rule_id: ovRuleId.value,
    date_from: ovRange.value?.[0],
    date_to: ovRange.value?.[1],
  })
}
async function loadExperiment() {
  if (expRuleId.value) exp.value = await fetchExperiment(expRuleId.value)
}
async function doRecompute() {
  if (!expRuleId.value) return
  recalcing.value = true
  try {
    await recompute(expRuleId.value)
    await loadExperiment()
  } finally {
    recalcing.value = false
  }
}
async function loadRanking() {
  loadingRank.value = true
  try { ranking.value = await rulesRanking() } finally { loadingRank.value = false }
}
async function loadPerf() {
  loadingPerf.value = true
  try { perf.value = await csPerformance() } finally { loadingPerf.value = false }
}

onMounted(async () => {
  rules.value = (await listRules({ page_size: 100 })).items
  await loadOverview()
})

watch(tab, (val) => {
  if (val === 'ranking' && !ranking.value.length) loadRanking()
  if (val === 'csperf' && !perf.value.length) loadPerf()
})
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; gap: 10px; }
.gap { margin-top: 4px; }
.signal-row { margin-top: 10px; }
.gap-tag { margin-right: 6px; }
</style>
