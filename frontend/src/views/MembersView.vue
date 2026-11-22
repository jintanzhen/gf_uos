<template>
  <div class="page">
    <div class="toolbar">
      <el-input
        v-model="search"
        :placeholder="isCs ? '搜索我的会员（昵称/实名/手机号）' : '搜索会员（昵称/实名/手机号/ext ID）'"
        clearable class="search"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>

    <el-table v-loading="loading" :data="items" stripe>
      <el-table-column prop="ext_member_id" label="会员 ID" width="100" />
      <el-table-column label="昵称" min-width="120">
        <template #default="{ row }">{{ row.nickname || '-' }}</template>
      </el-table-column>
      <el-table-column label="实名" min-width="110">
        <template #default="{ row }">{{ row.real_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="手机号" width="130">
        <template #default="{ row }">{{ row.mobile || '-' }}</template>
      </el-table-column>
      <el-table-column v-if="!isCs" label="归属客服" width="110">
        <template #default="{ row }">{{ row.cs_name || '公共池' }}</template>
      </el-table-column>
      <el-table-column label="生效中份额" width="110">
        <template #default="{ row }">{{ row.share_count ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="最少剩余次数" width="120">
        <template #default="{ row }">{{ row.min_remain_times ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="注册时间" width="120">
        <template #default="{ row }">{{ (row.register_time || '').slice(0, 10) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
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

    <el-drawer v-model="detailVisible" title="会员 360" size="50%">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small" class="block">
          <el-descriptions-item label="会员 ID">{{ detail.member.ext_member_id }}</el-descriptions-item>
          <el-descriptions-item label="昵称">{{ detail.member.nickname || '-' }}</el-descriptions-item>
          <el-descriptions-item label="实名">{{ detail.member.real_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="手机号">{{ detail.member.mobile || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="!isCs" label="归属客服">
            {{ detail.cs_name || '公共池' }}
          </el-descriptions-item>
          <el-descriptions-item label="注册时间">
            {{ (detail.member.register_time || '').slice(0, 10) }}
          </el-descriptions-item>
        </el-descriptions>

        <h4>会员标签</h4>
        <div class="tag-block">
          <template v-if="detail.tags && detail.tags.length">
            <el-tag v-for="t in detail.tags" :key="t.id" size="small" class="member-tag"
                    :type="t.tag_type === 'sys' ? 'primary' : 'warning'"
                    :effect="t.tag_type === 'sys' ? 'plain' : 'light'"
                    :closable="t.tag_type === 'manual'" @close="removeTag(t)">
              {{ t.tag_key }}{{ t.tag_value ? '·' + t.tag_value : '' }}{{ t.expire_at ? `（至${t.expire_at.slice(0, 10)}）` : '' }}
            </el-tag>
          </template>
          <span v-else class="dim">暂无标签</span>
        </div>
        <div class="tag-add">
          <div class="tag-select-wrap" @input="onTagInput">
            <el-select ref="tagSelectRef" v-model="newTagKey" filterable allow-create default-first-option
                       placeholder="选择或输入标签名（可自定义）" style="width: 200px" size="small">
              <el-option v-for="k in tagOptions" :key="k" :label="k" :value="k" />
            </el-select>
          </div>
          <el-date-picker v-model="newTagExpire" type="date" placeholder="到期时间（可选）"
                          value-format="YYYY-MM-DD" style="width: 160px" size="small" />
          <el-button size="small" type="primary" plain @click="addTag">添加标签</el-button>
        </div>
        <div class="tag-hint">先选/输入标签名再点「添加标签」；自定义标签直接输入文字后点添加即可（无需回车）</div>

        <h4>份额明细</h4>
        <el-table :data="detail.shares" size="small" border>
          <el-table-column label="份额类型" width="100">
            <template #default="{ row }">{{ shareLabel(row.share_type) }}</template>
          </el-table-column>
          <el-table-column prop="good_name" label="商品" min-width="140" show-overflow-tooltip />
          <el-table-column label="进度" width="90">
            <template #default="{ row }">{{ row.shipped_cnt }} / {{ row.total_cnt }}</template>
          </el-table-column>
          <el-table-column prop="remain_times" label="剩余" width="70" />
          <el-table-column prop="cycle_desc" label="配送周期" width="110" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">{{ statusLabel(row.order_status) }}</template>
          </el-table-column>
          <el-table-column label="配送期间" width="190">
            <template #default="{ row }">
              {{ (row.start_ship_date || '').slice(0, 10) }} ~ {{ (row.end_ship_date || '').slice(0, 10) }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  csMembers, csMemberDetail, opsMembers, opsMemberDetail,
  SHARE_TYPE_LABELS, ORDER_STATUS_LABELS,
  type MemberItem, type ShareItem,
} from '../api/members'
import {
  addManualTag, addManualTagOps, deleteManualTag, deleteManualTagOps,
  tagKeys, PRESET_TAG_KEYS, type MemberTag,
} from '../api/tags'
import { useAuthStore } from '../stores/auth'

const store = useAuthStore()
const isCs = computed(() => store.role === 'cs')

const search = ref('')
const items = ref<MemberItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const detailVisible = ref(false)
const detail = ref<{
  member: MemberItem; cs_name?: string | null; shares: ShareItem[]; tags?: MemberTag[]
} | null>(null)
const newTagKey = ref('')
const newTagExpire = ref<string | null>(null)
const knownKeys = ref<string[]>([])
const tagOptions = computed(() => Array.from(new Set([...PRESET_TAG_KEYS, ...knownKeys.value])))
const tagSelectRef = ref<{ $el?: HTMLElement; focus?: () => void } | null>(null)
const pendingQuery = ref('')

function onTagInput(e: Event) {
  const target = e.target as HTMLInputElement | null
  if (target?.tagName === 'INPUT') pendingQuery.value = target.value ?? ''
}

function resolveTagKey(): string {
  const selected = String(newTagKey.value ?? '').trim()
  if (selected) return selected
  // allow-create 下用户输入文字但未按回车/未选中选项时 v-model 仍为空，且点击按钮
  // 会让选择器失焦清空内部输入框；故用输入过程中实时捕获的文本兜底。
  return pendingQuery.value.trim()
}

function shareLabel(t?: string | null) {
  return t ? SHARE_TYPE_LABELS[t] || t : '-'
}
function statusLabel(s?: number | null) {
  return s === null || s === undefined ? '-' : ORDER_STATUS_LABELS[s] || String(s)
}

async function load() {
  loading.value = true
  try {
    const params = { search: search.value || undefined, page: page.value, page_size: pageSize }
    const res = isCs.value ? await csMembers(params) : await opsMembers(params)
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function openDetail(row: MemberItem) {
  detail.value = isCs.value
    ? { ...(await csMemberDetail(row.id)) }
    : { ...(await opsMemberDetail(row.id)) }
  detailVisible.value = true
  newTagKey.value = ''
  pendingQuery.value = ''
  newTagExpire.value = null
  if (!isCs.value) {
    try { knownKeys.value = await tagKeys() } catch { /* 词表拉取失败不阻断 */ }
  }
}

async function addTag() {
  if (!detail.value) return
  const key = resolveTagKey()
  if (!key) {
    ElMessage.warning('请先选择或输入标签名（自定义标签可直接输入文字后点添加）')
    tagSelectRef.value?.focus?.()
    return
  }
  const body = { tag_key: key, expire_at: newTagExpire.value || null }
  try {
    if (isCs.value) await addManualTag(detail.value.member.id, body)
    else await addManualTagOps(detail.value.member.id, body)
    ElMessage.success(`标签「${body.tag_key}」已添加`)
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { detail?: string } } })?.response
    ElMessage.error(resp?.data?.detail || '添加失败')
    return
  }
  await openDetail(detail.value.member as MemberItem)
}

async function removeTag(t: MemberTag) {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`删除标签「${t.tag_key}」？删除将留痕审计。`, '确认删除', { type: 'warning' })
  } catch { return }
  if (isCs.value) await deleteManualTag(t.id)
  else await deleteManualTagOps(t.id)
  ElMessage.success('已删除')
  await openDetail(detail.value.member as MemberItem)
}

onMounted(load)
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; gap: 10px; }
.search { max-width: 360px; }
.pager { justify-content: flex-end; }
.block { margin-bottom: 14px; }
h4 { margin: 8px 0; color: #606266; }
.tag-block { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; min-height: 24px; }
.member-tag { margin-right: 0; }
.tag-add { display: flex; gap: 8px; margin-bottom: 4px; }
.tag-hint { color: #909399; font-size: 12px; margin-bottom: 14px; }
.dim { color: #909399; font-size: 12px; }
</style>
