import http from './http'

export interface PoolTask {
  id: number; member_id: number; rule_id: number
  plan_time: string | null; expire_deadline: string | null
}

export interface BlacklistRow {
  id: number; member_id: number; is_active: boolean
  until_date: string | null; reason: string | null
}

export const poolTasks = (page = 1, pageSize = 20) =>
  http.get<never, { total: number; items: PoolTask[] }>('/ops/pool', { params: { page, page_size: pageSize } })

export const claimTask = (id: number) => http.post<never, { id: number; cs_id: number }>(`/ops/pool/${id}/claim`)

export const listBlacklist = () => http.get<never, BlacklistRow[]>('/ops/blacklist')

export const addBlacklist = (body: { member_id: number; until_date?: string; reason?: string }) =>
  http.post<never, { member_id: number; is_active: boolean; cancelled_tasks: number }>('/ops/blacklist', body)

export const unblock = (id: number) =>
  http.post<never, { id: number; is_active: boolean }>(`/ops/blacklist/${id}/unblock`)
