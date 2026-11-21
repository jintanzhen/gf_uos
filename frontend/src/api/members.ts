import http from './http'

// ---------- 类型 ----------
export interface MemberItem {
  id: number
  ext_member_id: number
  nickname: string | null
  real_name: string | null
  mobile: string | null
  register_time: string | null
  share_count?: number
  min_remain_times?: number | null
  cs_name?: string | null
}

export interface ShareItem {
  id: number
  share_type: string | null
  good_name: string | null
  total_cnt: number | null
  shipped_cnt: number | null
  remain_times: number | null
  cycle_desc: string | null
  start_ship_date: string | null
  end_ship_date: string | null
  order_status: number | null
}

export interface Page<T> { total: number; page: number; page_size: number; items: T[] }

// ---------- 客服端（我的会员） ----------
export const csMembers = (params: { search?: string; page?: number; page_size?: number }) =>
  http.get<never, Page<MemberItem>>('/cs/members', { params })

export const csMemberDetail = (id: number) =>
  http.get<never, { member: MemberItem; shares: ShareItem[] }>(`/cs/members/${id}`)

// ---------- 运营端（全量检索） ----------
export const opsMembers = (params: { search?: string; page?: number; page_size?: number }) =>
  http.get<never, Page<MemberItem>>('/ops/members', { params })

export const opsMemberDetail = (id: number) =>
  http.get<never, { member: MemberItem; cs_name: string | null; shares: ShareItem[] }>(`/ops/members/${id}`)

export const SHARE_TYPE_LABELS: Record<string, string> = {
  shucai: '蔬菜份额',
  doufu: '豆制品份额',
  douya: '豆芽份额',
}

export const ORDER_STATUS_LABELS: Record<number, string> = {
  0: '已删除', 1: '待审核', 2: '进行中', 3: '已完结', 4: '已暂停', 5: '异常', 6: '仅展示',
}
