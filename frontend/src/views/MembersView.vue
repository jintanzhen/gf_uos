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
import {
  csMembers, csMemberDetail, opsMembers, opsMemberDetail,
  SHARE_TYPE_LABELS, ORDER_STATUS_LABELS,
  type MemberItem, type ShareItem,
} from '../api/members'
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
const detail = ref<{ member: MemberItem; cs_name?: string | null; shares: ShareItem[] } | null>(null)

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
</style>
