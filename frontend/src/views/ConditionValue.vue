<template>
  <el-select v-if="op === 'in'" v-model="multiValue" multiple filterable allow-create
             default-first-option placeholder="输入多个值，回车分隔" style="width: 240px" size="small" />
  <template v-else-if="op === 'between'">
    <el-input-number v-model="rangeLo" size="small" style="width: 110px" />
    <span class="sep">~</span>
    <el-input-number v-model="rangeHi" size="small" style="width: 110px" />
  </template>
  <el-select v-else-if="field === 'share_type'" :model-value="modelValue" size="small" style="width: 160px"
             @update:model-value="emit('update:modelValue', $event)">
    <el-option label="蔬菜份额" value="shucai" />
    <el-option label="豆制品份额" value="doufu" />
    <el-option label="豆芽份额" value="douya" />
  </el-select>
  <el-select v-else-if="field === 'order_status'" :model-value="modelValue" size="small" style="width: 160px"
             @update:model-value="emit('update:modelValue', $event)">
    <el-option label="已删除" :value="0" />
    <el-option label="进行中" :value="2" />
    <el-option label="已完结" :value="3" />
  </el-select>
  <el-input-number v-else-if="numeric" :model-value="Number(modelValue) || 0" size="small" style="width: 150px"
                   @update:model-value="emit('update:modelValue', $event)" />
  <el-select v-else-if="field === 'tag'" filterable allow-create default-first-option
             placeholder="选择或输入标签" style="width: 200px" size="small"
             :model-value="String(modelValue ?? '')"
             @update:model-value="emit('update:modelValue', $event)">
    <el-option v-for="k in tagOptions" :key="k" :label="k" :value="k" />
  </el-select>
  <el-input v-else :model-value="String(modelValue ?? '')" size="small" style="width: 200px"
            @update:model-value="emit('update:modelValue', $event)" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { FIELDS, type ConditionOp } from '../api/rules'
import { PRESET_TAG_KEYS, tagKeys } from '../api/tags'

const props = defineProps<{ modelValue: unknown; field: string; op: ConditionOp }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

const numeric = computed(() => FIELDS[props.field]?.numeric)

const knownKeys = ref<string[]>([])
const tagOptions = computed(() => Array.from(new Set([...PRESET_TAG_KEYS, ...knownKeys.value])))
onMounted(async () => {
  try { knownKeys.value = await tagKeys() } catch { /* 词表拉取失败不阻断 */ }
})

const multiValue = ref<string[]>(Array.isArray(props.modelValue) ? props.modelValue.map(String) : [])
watch(multiValue, (v) => {
  if (props.op === 'in') emit('update:modelValue', v)
})

const rangeLo = ref<number>(Array.isArray(props.modelValue) ? Number(props.modelValue[0]) || 0 : 0)
const rangeHi = ref<number>(Array.isArray(props.modelValue) ? Number(props.modelValue[1]) || 0 : 0)
watch([rangeLo, rangeHi], () => {
  if (props.op === 'between') emit('update:modelValue', [rangeLo.value, rangeHi.value])
})

watch(() => props.op, (op) => {
  if (op === 'in' && !Array.isArray(props.modelValue)) multiValue.value = []
  if (op === 'between' && !Array.isArray(props.modelValue)) { rangeLo.value = 0; rangeHi.value = 0 }
})
</script>

<style scoped>
.sep { margin: 0 6px; color: #909399; }
</style>
