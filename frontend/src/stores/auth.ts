import { defineStore } from 'pinia'
import { login as apiLogin, me as apiMe } from '../api/auth'

export type Role = 'cs' | 'ops' | 'admin'

export interface OperatorInfo {
  id: number
  name: string
  role: Role
  ext_cs_id: number | null
  status: string
}

const TOKEN_KEY = 'greenos_token'
const OPERATOR_KEY = 'greenos_operator'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    operator: JSON.parse(localStorage.getItem(OPERATOR_KEY) || 'null') as OperatorInfo | null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    role: (s) => s.operator?.role ?? null,
  },
  actions: {
    async login(name: string, password: string) {
      const res = await apiLogin(name, password)
      this.token = res.access_token
      this.operator = res.operator
      localStorage.setItem(TOKEN_KEY, res.access_token)
      localStorage.setItem(OPERATOR_KEY, JSON.stringify(res.operator))
    },
    async refreshMe() {
      this.operator = await apiMe()
      localStorage.setItem(OPERATOR_KEY, JSON.stringify(this.operator))
    },
    logout() {
      this.token = ''
      this.operator = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(OPERATOR_KEY)
    },
  },
})
