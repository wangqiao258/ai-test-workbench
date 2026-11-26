import type { RunStatus } from '../../types'

export const STATUS_OPTIONS: Array<{ value: 'all' | RunStatus; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'passed', label: '通过' },
  { value: 'failed', label: '失败' },
  { value: 'error', label: '错误' },
  { value: 'skipped', label: '跳过' },
]

export const FRAMEWORK_LABELS: Record<string, string> = {
  pytest: 'pytest',
  tavern: 'Tavern',
  postman: 'Postman',
  playwright: 'Playwright',
  cypress: 'Cypress',
}
