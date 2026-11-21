import http from './http'
import type { Page, ShareItem } from './members'

export type TaskZone = 'overdue' | 'today' | 'upcoming'
export type TaskResult = 'renewed' | 'considering' | 'not_now' | 'unreachable' | 'refused' | 'other'

export interface TaskItem {
  id: number
  member_id: number
  member_name: string | null
  share_type: string | null
  remain_times: number | null
  plan_time: string | null
  expire_deadline: string | null
  content_preview: string
  copied: boolean
}

export interface TaskDetail {
  task: {
    id: number; status: string; result: string | null; remark: string | null
    plan_time: string | null; copied_at: string | null; created_at: string | null
  }
  member: { id: number; ext_member_id: number; nickname: string | null; real_name: string | null } | null
  share: ShareItem | null
  content: string
  touch_history: { id: number; result: string; completed_at: string }[]
}

export interface CsSummary {
  should_contact: number
  contacted: number
  overdue: number
  result_distribution: Record<string, string | number>
}

export const RESULT_LABELS: Record<TaskResult, string> = {
  renewed: '已续订',
  considering: '考虑中',
  not_now: '暂不续订',
  unreachable: '联系不上',
  refused: '会员拒绝',
  other: '其他',
}

export const csTasks = (zone: TaskZone, page = 1, pageSize = 20) =>
  http.get<never, Page<TaskItem>>('/cs/tasks', { params: { zone, page, page_size: pageSize } })

export const csTaskDetail = (id: number) => http.get<never, TaskDetail>(`/cs/tasks/${id}`)

export const csTaskCopy = (id: number) =>
  http.post<never, { copied_at: string }>(`/cs/tasks/${id}/copy`)

export const csTaskComplete = (id: number, result: TaskResult, remark?: string) =>
  http.post<never, unknown>(`/cs/tasks/${id}/complete`, { result, remark: remark || null })

export const csTaskCancel = (id: number, reason: string) =>
  http.post<never, unknown>(`/cs/tasks/${id}/cancel`, { reason })

export const csTaskReschedule = (id: number, plan_time: string, reason: string) =>
  http.post<never, unknown>(`/cs/tasks/${id}/reschedule`, { plan_time, reason })

export const csSummary = () => http.get<never, CsSummary>('/cs/summary')
