import http from './http'

export interface Overview {
  generated: number; done: number; pending: number; cancelled: number
  expired: number; overdue: number
  completion_rate: number | null
  avg_latency_seconds: number | null
  result_distribution: Record<string, number>
  by_day: { date: string; generated: number; done: number }[]
}

export interface Experiment {
  rule: { id: number; name: string; attribution_days: number; experiment_ratio: number }
  exp: {
    generated: number; done: number; contact_rate: number | null
    renewals: number; renewals_of_done: number
    renew_rate_of_done: number | null; renew_rate_of_generated: number | null
    signal_distribution: Record<string, number>
  }
  ctrl: { members: number; renewals: number; renew_rate: number | null }
  diff: number | null
  relative_lift: number | null
  p_value: number | null
  conclusion_reliable: boolean
  warning: string | null
}

export interface RankRow {
  rule_id: number; rule_name: string; status: string
  exp: Experiment['exp']; ctrl: Experiment['ctrl']
  diff: number | null; relative_lift: number | null
  p_value: number | null; conclusion_reliable: boolean
}

export interface CsPerf {
  cs_id: number; cs_name: string; generated: number; done: number
  completion_rate: number; on_time_rate: number | null
  avg_latency_seconds: number | null; attributed_renewals: number
}

export const overview = (params?: { rule_id?: number; cs_id?: number; date_from?: string; date_to?: string }) =>
  http.get<never, Overview>('/ops/reports/overview', { params })

export const experiment = (ruleId: number) =>
  http.get<never, Experiment>(`/ops/reports/experiment/${ruleId}`)

export const rulesRanking = () => http.get<never, RankRow[]>('/ops/reports/rules-ranking')

export const csPerformance = (params?: { date_from?: string; date_to?: string }) =>
  http.get<never, CsPerf[]>('/ops/reports/cs-performance', { params })

export const recompute = (ruleId: number) =>
  http.post<never, { status: string; detected: number; windows_closed: number }>(
    '/ops/reports/recompute', { rule_id: ruleId })

export const SIGNAL_LABELS: Record<string, string> = {
  new_order: '新份额订单',
  match_order: '订单关联',
  remain_rebound: '剩余次数回升',
  unknown: '未知',
}

export const RESULT_LABELS: Record<string, string> = {
  renewed: '已续订', considering: '考虑中', not_now: '暂不续订',
  unreachable: '联系不上', refused: '会员拒绝', other: '其他',
}
