import http from './http'
import type { OperatorInfo } from '../stores/auth'

interface TokenResponse {
  access_token: string
  token_type: string
  operator: OperatorInfo
}

export async function login(name: string, password: string): Promise<TokenResponse> {
  return http.post('/auth/login', { name, password })
}

export async function me(): Promise<OperatorInfo> {
  return http.get('/auth/me')
}
