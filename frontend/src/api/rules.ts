import http from './http'

export type ConditionOp = 'eq' | 'ne' | 'lte' | 'gte' | 'between' | 'in' | 'contains' | 'has'

export interface Condition { field: string; op: ConditionOp; value: unknown }
export interface ConditionGroup { logic: 'and' | 'or'; conditions: (Condition | ConditionGroup)[] }
/** 编辑器内的条件组：子条件全部为叶子条件（两层嵌套限制，PRD 5.4.1） */
export interface EditorConditionGroup { logic: 'and' | 'or'; conditions: Condition[] }

export interface Rule {
  id: number
  name: string
  conditions: ConditionGroup
  exec_time: string
  freq: 'daily' | 'weekly'
  weekdays: string | null
  plan_time: string
  template: string
  benefit_text: string | null
  freq_n_days: number
  freq_m_times: number
  experiment_enabled: boolean
  experiment_ratio: number
  attribution_days: number
  priority: number
  status: 'enabled' | 'disabled'
  start_date: string | null
  end_date: string | null
  updated_at: string
}

export interface ScanLog {
  id: number; scan_at: string; hit_count: number; exp_generated: number
  ctrl_skipped: number; freq_skipped: number; blacklist_skipped: number
  dedup_skipped: number; conflict_skipped: number
  status: string; error: string | null; duration_ms: number
}

export interface PreviewResult {
  hit_count: number; member_count: number; exp_count: number; ctrl_count: number
  min_sample_warning: boolean
  sample: { member_id: number; share_detail_id: number }[]
}

// 条件字段元数据（与后端 FIELDS 对齐，PRD 5.4.1）
export const FIELDS: Record<string, { label: string; ops: ConditionOp[]; numeric: boolean }> = {
  remain_times: { label: '剩余次数', ops: ['eq', 'ne', 'lte', 'gte', 'between', 'in'], numeric: true },
  share_type: { label: '份额类型', ops: ['eq', 'ne', 'in'], numeric: false },
  order_status: { label: '订单状态', ops: ['eq', 'ne', 'in'], numeric: true },
  good_name: { label: '商品名称', ops: ['eq', 'contains', 'in'], numeric: false },
  tag: { label: '会员标签', ops: ['has'], numeric: false },
  cs_id: { label: '归属客服ID', ops: ['eq'], numeric: true },
  register_days: { label: '注册天数', ops: ['gte', 'lte', 'between'], numeric: true },
}

export const OP_LABELS: Record<ConditionOp, string> = {
  eq: '等于', ne: '不等于', lte: '小于等于', gte: '大于等于',
  between: '介于', in: '属于', contains: '包含', has: '拥有标签',
}

export const listRules = (params?: { status?: string; search?: string; page?: number; page_size?: number }) =>
  http.get<never, { total: number; items: Rule[] }>('/ops/rules', { params })

export const getRule = (id: number) => http.get<never, Rule>(`/ops/rules/${id}`)

export const createRule = (body: Partial<Rule>) => http.post<never, Rule>('/ops/rules', body)

export const updateRule = (id: number, body: Partial<Rule>) => http.put<never, Rule>(`/ops/rules/${id}`, body)

export const toggleRule = (id: number) => http.post<never, Rule>(`/ops/rules/${id}/toggle`)

export const duplicateRule = (id: number) => http.post<never, Rule>(`/ops/rules/${id}/duplicate`)

export const deleteRule = (id: number) => http.delete<never, unknown>(`/ops/rules/${id}`)

export const previewRule = (id: number) => http.post<never, PreviewResult>(`/ops/rules/${id}/preview`)

export const runScan = (id: number) => http.post<never, Record<string, unknown>>(`/ops/rules/${id}/run-scan`)

export const scanLogs = (id: number, limit = 20) =>
  http.get<never, ScanLog[]>(`/ops/rules/${id}/scan-logs`, { params: { limit } })
