import http from './http'

export interface MemberTag {
  id: number
  tag_type: 'sys' | 'manual'
  tag_key: string
  tag_value: string | null
  expire_at: string | null
  created_by: number | null
}

export const addManualTag = (memberId: number, body: { tag_key: string; expire_at?: string | null }) =>
  http.post<never, { id: number; tag_key: string }>(`/cs/members/${memberId}/tags`, body)

export const deleteManualTag = (tagId: number) =>
  http.delete<never, { deleted: number }>(`/cs/tags/${tagId}`)

export const addManualTagOps = (memberId: number, body: { tag_key: string; expire_at?: string | null }) =>
  http.post<never, { id: number; tag_key: string }>(`/ops/members/${memberId}/tags`, body)

export const deleteManualTagOps = (tagId: number) =>
  http.delete<never, { deleted: number }>(`/ops/tags/${tagId}`)

export const tagKeys = () => http.get<never, string[]>('/ops/tags/keys')

export const recomputeTags = () =>
  http.post<never, Record<string, unknown>>('/ops/tags/recompute')

/** 前端预置常用词表（与后端允许自定义并存） */
export const PRESET_TAG_KEYS = ['价格敏感', '只收微信', '勿扰', '新客待跟进']
