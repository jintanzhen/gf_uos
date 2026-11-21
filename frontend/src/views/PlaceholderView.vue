<template>
  <el-card class="placeholder" shadow="never">
    <template #header>
      <span class="title">{{ route.meta.title }}</span>
    </template>
    <el-empty :description="description">
      <template #image>
        <el-icon class="big-icon"><Odometer /></el-icon>
      </template>
      <el-text type="info" size="small">
        按里程碑规划，本模块将在后续阶段交付（详见 architecture.md §9）
      </el-text>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Odometer } from '@element-plus/icons-vue'

const route = useRoute()
const description = computed(() => `${route.meta.title ?? '页面'} · 占位页`)
</script>

<style scoped>
.placeholder { min-height: 420px; }
.title { font-size: 16px; font-weight: 600; }
.big-icon { font-size: 64px; color: #c0c4cc; }
</style>
