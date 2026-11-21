<template>
  <div class="login-page">
    <div class="orb orb-1" />
    <div class="orb orb-2" />
    <div class="orb orb-3" />

    <div class="login-card">
      <div class="brand">
        <div class="brand-logo">G</div>
        <div>
          <h1 class="brand-title">运营支持系统</h1>
          <p class="brand-sub">Green-OS · 让每一次触达都有依据</p>
        </div>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="submit"
      >
        <el-form-item prop="name">
          <el-input v-model="form.name" placeholder="账号" :prefix-icon="User" autocomplete="username" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            :prefix-icon="Lock"
            autocomplete="current-password"
          />
        </el-form-item>
        <el-button
          class="submit-btn"
          type="primary"
          size="large"
          :loading="loading"
          @click="submit"
        >
          {{ loading ? '登录中…' : '登 录' }}
        </el-button>
      </el-form>
    </div>

    <p class="footer-note">M0 骨架 · 服务于份额续订提醒与运营效果验证</p>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const store = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ name: '', password: '' })

const rules: FormRules = {
  name: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await store.login(form.name, form.password)
    ElMessage.success(`欢迎，${store.operator?.name}`)
    router.push('/dashboard')
  } catch (e: unknown) {
    const detail =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '登录失败，请稍后重试'
    ElMessage.error(detail)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #1d2b35 0%, #24435a 45%, #2f6fa2 100%);
}

/* 背景装饰光球，带缓慢漂浮动画 */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.45;
  animation: drift 14s ease-in-out infinite alternate;
}
.orb-1 { width: 420px; height: 420px; background: #409eff; top: -120px; left: -80px; }
.orb-2 { width: 320px; height: 320px; background: #67c23a; bottom: -100px; right: -60px; animation-delay: -5s; }
.orb-3 { width: 220px; height: 220px; background: #7a5cff; top: 40%; right: 18%; animation-delay: -9s; }

@keyframes drift {
  from { transform: translate(0, 0) scale(1); }
  to   { transform: translate(40px, 30px) scale(1.08); }
}

.login-card {
  position: relative;
  z-index: 1;
  width: 400px;
  padding: 44px 40px 36px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(18px);
  box-shadow: 0 24px 60px rgba(10, 25, 41, 0.45);
  animation: card-in 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes card-in {
  from { opacity: 0; transform: translateY(24px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

.brand { display: flex; align-items: center; gap: 14px; margin-bottom: 32px; }
.brand-logo {
  width: 52px; height: 52px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 28px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #409eff, #1d2b35);
  box-shadow: 0 8px 20px rgba(64, 158, 255, 0.4);
}
.brand-title { font-size: 20px; font-weight: 600; color: #303133; }
.brand-sub { font-size: 12px; color: #909399; margin-top: 4px; }

.submit-btn {
  width: 100%;
  margin-top: 4px;
  letter-spacing: 4px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.submit-btn:not(:disabled):hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(64, 158, 255, 0.35); }

.footer-note {
  position: relative;
  z-index: 1;
  margin-top: 28px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
}
</style>
