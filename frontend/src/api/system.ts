import http from './http'

export interface SyncLog {
  id: number; sync_type: string; status: string
  total_source: number | null; total_local: number | null
  started_at: string; finished_at: string | null; error: string | null
}

export const syncLogs = (limit = 30) =>
  http.get<never, SyncLog[]>('/admin/sync-logs', { params: { limit } })

export const runSync = (type: string) =>
  http.post<never, { started: boolean }>('/admin/sync/all/run', null, { params: { type } })

// ---- 人员管理（方案 B）----

export interface OperatorRow {
  id: number
  name: string
  role: 'cs' | 'ops' | 'admin'
  status: 'active' | 'left'
  ext_cs_id: number | null
  phone: string | null
  account_ready: boolean
  binding_count: number
  task_count: number
}

export const listOperators = () =>
  http.get<never, OperatorRow[]>('/admin/operators')

export const resetPassword = (id: number, password: string) =>
  http.post<never, { activated: boolean }>(`/admin/operators/${id}/reset-password`, { password })

export const setOperatorStatus = (id: number, status: 'active' | 'left') =>
  http.post<never, { note: string | null }>(`/admin/operators/${id}/status`, { status })
