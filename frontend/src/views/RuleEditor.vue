<template>
  <el-dialog v-model="visible" :title="rule ? '编辑规则' : '新建规则'" width="720px" :close-on-click-modal="false">
    <el-form :model="form" label-width="100px">
      <el-form-item label="规则名称" required>
        <el-input v-model="form.name" maxlength="100" placeholder="如：蔬菜份额续订提醒" />
      </el-form-item>

      <!-- 命中条件（两层嵌套：根组 AND/OR + 可选一个子组） -->
      <el-form-item label="命中条件" required>
        <div class="cond-root">
          <div class="logic-row">
            <span>满足以下</span>
            <el-radio-group v-model="form.conditions.logic" size="small">
              <el-radio-button value="and">全部条件（AND）</el-radio-button>
              <el-radio-button value="or">任一条件（OR）</el-radio-button>
            </el-radio-group>
          </div>

          <div v-for="(line, idx) in lines" :key="idx" class="cond-line">
            <!-- 子组 -->
            <template v-if="line.type === 'group'">
              <div class="group-box">
                <div class="group-head">
                  <el-radio-group v-model="line.group!.logic" size="small">
                    <el-radio-button value="and">全部（AND）</el-radio-button>
                    <el-radio-button value="or">任一（OR）</el-radio-button>
                  </el-radio-group>
                  <el-button size="small" text type="danger" @click="removeLine(idx)">删除子组</el-button>
                </div>
                <div v-for="(c, ci) in line.group!.conditions" :key="ci" class="cond-row">
                  <el-select v-model="c.field" size="small" style="width: 130px" @change="onFieldChange(c)">
                    <el-option v-for="(meta, key) in FIELDS" :key="key" :label="meta.label" :value="key" />
                  </el-select>
                  <el-select v-model="c.op" size="small" style="width: 110px">
                    <el-option v-for="op in FIELDS[c.field]?.ops || []" :key="op" :label="OP_LABELS[op]" :value="op" />
                  </el-select>
                  <ConditionValue v-model="c.value" :field="c.field" :op="c.op" />
                  <el-button size="small" text type="danger" @click="line.group!.conditions.splice(ci, 1)">删</el-button>
                </div>
                <el-button size="small" text type="primary" @click="addSubCondition(line.group!)">+ 子条件</el-button>
              </div>
            </template>

            <!-- 单条件 -->
            <template v-else>
              <el-select v-model="line.cond!.field" size="small" style="width: 130px" @change="onFieldChange(line.cond!)">
                <el-option v-for="(meta, key) in FIELDS" :key="key" :label="meta.label" :value="key" />
              </el-select>
              <el-select v-model="line.cond!.op" size="small" style="width: 110px">
                <el-option v-for="op in FIELDS[line.cond!.field]?.ops || []" :key="op" :label="OP_LABELS[op]" :value="op" />
              </el-select>
              <ConditionValue v-model="line.cond!.value" :field="line.cond!.field" :op="line.cond!.op" />
              <el-button size="small" text type="danger" @click="removeLine(idx)">删</el-button>
            </template>
          </div>

          <div class="add-row">
            <el-button size="small" @click="addCondition">+ 条件</el-button>
            <el-button size="small" :disabled="hasGroup" @click="addGroup">+ 条件组（二层嵌套）</el-button>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="触发时间" required>
        <el-time-select v-model="form.exec_time" start="00:00" end="23:30" step="00:30"
                        placeholder="每日触发时刻（如 09:30）" style="width: 180px" />
        <el-radio-group v-model="form.freq" class="gap-left" @change="form.weekdays = null">
          <el-radio value="daily">每日</el-radio>
          <el-radio value="weekly">每周</el-radio>
        </el-radio-group>
        <el-select v-if="form.freq === 'weekly'" v-model="weekdayArr" multiple collapse-tags
                   placeholder="选择星期" style="width: 200px" class="gap-left">
          <el-option v-for="(label, idx) in WEEKDAYS" :key="idx" :label="label" :value="String(idx)" />
        </el-select>
      </el-form-item>

      <el-form-item label="计划时间" required>
        <el-time-select v-model="form.plan_time" start="00:00" end="23:30" step="00:30"
                        placeholder="任务计划联系时刻" style="width: 180px" />
      </el-form-item>

      <el-form-item label="内容模板" required>
        <el-input v-model="form.template" type="textarea" :rows="4"
                  placeholder="{会员昵称}您好，我是您的专属客服{客服名}。您的{份额类型}还剩{剩余次数}次（共{总次数}次），{续订权益}，需要续订随时回复我" />
        <div class="var-hint">
          可用变量：
          <el-tag v-for="v in VARIABLES" :key="v" size="small" type="info" class="var-tag"
                  @click="form.template += '{' + v + '}'">{{ v }}</el-tag>
        </div>
      </el-form-item>

      <el-form-item label="续订权益">
        <el-input v-model="form.benefit_text" maxlength="200" placeholder="{续订权益} 变量的静态文本，如：本月底前续订立减30元" />
      </el-form-item>

      <el-form-item label="频控" required>
        每
        <el-input-number v-model="form.freq_n_days" :min="7" :max="365" size="small" class="gap-x" />
        天最多
        <el-input-number v-model="form.freq_m_times" :min="1" :max="4" size="small" class="gap-x" />
        次（按会员计数，硬上限 4 次 / 7 天）
      </el-form-item>

      <el-form-item label="对照组">
        <el-switch v-model="form.experiment_enabled" />
        <template v-if="form.experiment_enabled">
          比例
          <el-input-number v-model="form.experiment_ratio" :min="10" :max="50" size="small" class="gap-x" />
          %（10%~50%，默认 20）
        </template>
      </el-form-item>

      <el-form-item label="归因窗口">
        <el-input-number v-model="form.attribution_days" :min="1" :max="365" size="small" />
        天（任务完成后 N 天内的续订归因于本任务，默认 30）
      </el-form-item>

      <el-form-item label="优先级">
        <el-input-number v-model="form.priority" size="small" />
        <span class="dim">数值越大越先占用（BR-09 互斥仲裁顺序）</span>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存（保存即生效）</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ConditionValue from './ConditionValue.vue'
import {
  createRule, updateRule, FIELDS, OP_LABELS,
  type Condition, type ConditionGroup, type EditorConditionGroup, type Rule,
} from '../api/rules'

const VARIABLES = ['会员昵称', '客服名', '客服二维码', '份额类型', '商品名', '剩余次数', '总次数', '配送周期', '续订权益']
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

type Line =
  | { type: 'cond'; cond: Condition }
  | { type: 'group'; group: EditorConditionGroup }

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ rule: Rule | null }>()
const emit = defineEmits<{ saved: [] }>()

const defaultForm = () => ({
  name: '',
  conditions: { logic: 'and', conditions: [] } as ConditionGroup,
  exec_time: '09:30',
  freq: 'daily' as 'daily' | 'weekly',
  weekdays: null as string | null,
  plan_time: '10:00',
  template: '{会员昵称}您好，我是您的专属客服{客服名}。您的{份额类型}还剩{剩余次数}次（共{总次数}次），{续订权益}，需要续订随时回复我',
  benefit_text: '',
  freq_n_days: 7,
  freq_m_times: 2,
  experiment_enabled: true,
  experiment_ratio: 20,
  attribution_days: 30,
  priority: 0,
})

const form = ref(defaultForm())
const lines = ref<Line[]>([])
const saving = ref(false)
const weekdayArr = ref<string[]>([])

const hasGroup = computed(() => lines.value.some((l) => l.type === 'group'))

function defaultCondition(): Condition {
  return { field: 'remain_times', op: 'lte', value: 4 }
}

function addCondition() {
  lines.value.push({ type: 'cond', cond: defaultCondition() })
}
function addGroup() {
  lines.value.push({ type: 'group', group: { logic: 'or', conditions: [defaultCondition()] } })
}
function addSubCondition(group: EditorConditionGroup) {
  group.conditions.push(defaultCondition())
}
function removeLine(idx: number) {
  lines.value.splice(idx, 1)
}
function onFieldChange(c: Condition) {
  c.op = (FIELDS[c.field]?.ops || ['eq'])[0]
  c.value = FIELDS[c.field]?.numeric ? 0 : ''
}

function hydrate(rule: Rule | null) {
  if (!rule) {
    form.value = defaultForm()
    lines.value = []
    weekdayArr.value = []
    addCondition()
    return
  }
  form.value = {
    name: rule.name,
    conditions: rule.conditions,
    exec_time: rule.exec_time,
    freq: rule.freq,
    weekdays: rule.weekdays,
    plan_time: rule.plan_time,
    template: rule.template,
    benefit_text: rule.benefit_text || '',
    freq_n_days: rule.freq_n_days,
    freq_m_times: rule.freq_m_times,
    experiment_enabled: rule.experiment_enabled,
    experiment_ratio: rule.experiment_ratio,
    attribution_days: rule.attribution_days,
    priority: rule.priority,
  }
  weekdayArr.value = (rule.weekdays || '').split(',').filter(Boolean)
  // 重建编辑行：顶层条件中嵌套的识别为子组
  lines.value = (rule.conditions.conditions || []).map((item) =>
    'logic' in item
      ? { type: 'group', group: { logic: (item as ConditionGroup).logic,
                                  conditions: (item as ConditionGroup).conditions as Condition[] } }
      : { type: 'cond', cond: item as Condition })
}

watch(visible, (v) => {
  if (v) hydrate(props.rule)
})

async function submit() {
  const f = form.value
  if (!f.name.trim()) { ElMessage.warning('请填写规则名称'); return }
  if (!lines.value.length) { ElMessage.warning('至少一个命中条件'); return }
  if (f.freq === 'weekly' && !weekdayArr.value.length) { ElMessage.warning('每周规则需选择星期'); return }

  f.conditions.conditions = lines.value.map((l) =>
    l.type === 'cond' ? l.cond : l.group)

  saving.value = true
  try {
    const payload = { ...f, weekdays: f.freq === 'weekly' ? weekdayArr.value.join(',') : null }
    if (props.rule) {
      await updateRule(props.rule.id, payload)
      ElMessage.success('规则已更新')
    } else {
      await createRule(payload)
      ElMessage.success('规则已创建并启用')
    }
    visible.value = false
    emit('saved')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.cond-root {
  width: 100%; padding: 10px 12px; background: #f8fafc;
  border: 1px solid #e4e7ed; border-radius: 8px;
  display: flex; flex-direction: column; gap: 8px;
}
.logic-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #606266; }
.cond-line { display: flex; gap: 6px; align-items: flex-start; }
.cond-row { display: flex; gap: 6px; margin-bottom: 6px; }
.group-box {
  flex: 1; padding: 8px 10px; border: 1px dashed #c0c4cc; border-radius: 6px;
  background: #fff;
}
.group-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.add-row { display: flex; gap: 8px; }
.var-hint { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; font-size: 12px; color: #909399; }
.var-tag { cursor: pointer; }
.gap-left { margin-left: 10px; }
.gap-x { margin: 0 6px; }
.dim { color: #909399; font-size: 12px; margin-left: 8px; }
</style>
