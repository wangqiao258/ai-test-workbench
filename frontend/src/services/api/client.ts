import type { BackendUser, LoginResponse, Page } from './contracts'

/**
 * HTTP 客户端与登录会话。
 * 数据出入口只对接真实后端，组件层不感知请求细节。
 */
export const BASE_URL = '/api/v1'
const TOKEN_KEY = 'ai-test-workbench:token'

export interface Session {
  user: BackendUser
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function hasToken(): boolean {
  return Boolean(getToken())
}

export function logout(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 忽略存储不可用的场景。
  }
}

export async function request(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers)
  headers.set('content-type', 'application/json')
  const token = getToken()
  if (token) headers.set('authorization', `Bearer ${token}`)

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    let message = `请求失败：${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as {
        error?: { message?: string }
      }
      if (body.error?.message) message = body.error.message
    } catch {
      // 非 JSON 错误响应时保留默认提示。
    }
    if (response.status === 401 && !path.startsWith('/auth/login')) {
      logout()
      window.dispatchEvent(new Event('workbench:unauthorized'))
    }
    throw new Error(message)
  }
  return response
}

export async function fetchJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await request(path, init)
  return (await response.json()) as T
}

export async function fetchAllPages<T>(
  path: string,
  pageSize = 100,
  maxPages = 20,
): Promise<T[]> {
  const items: T[] = []
  const separator = path.includes('?') ? '&' : '?'
  for (let page = 1; page <= maxPages; page += 1) {
    const data = await fetchJson<Page<T>>(
      `${path}${separator}page=${page}&page_size=${pageSize}`,
    )
    items.push(...data.items)
    if (items.length >= data.total || data.items.length === 0) break
  }
  return items
}

export async function login(
  email: string,
  password: string,
): Promise<Session> {
  const result = await fetchJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  localStorage.setItem(TOKEN_KEY, result.accessToken)
  return { user: result.user }
}

export async function fetchSession(): Promise<Session> {
  const result = await fetchJson<{ user: BackendUser }>('/auth/me')
  return { user: result.user }
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await fetchJson<{ status: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ currentPassword, newPassword }),
  })
}
