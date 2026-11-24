import type {
  DefectStatus,
  FindingType,
  RunStatus,
  Severity,
  Verdict,
} from '../types'

export const severityLabel: Record<Severity, string> = {
  blocker: '阻塞',
  critical: '严重',
  major: '一般',
  minor: '轻微',
}

export const statusLabel: Record<DefectStatus, string> = {
  new: '待处理',
  confirmed: '已确认',
  fixing: '修复中',
  fixed: '待验证',
  closed: '已关闭',
}

export const runStatusLabel: Record<RunStatus, string> = {
  passed: '通过',
  failed: '失败',
  skipped: '跳过',
  error: '错误',
}

export const findingTypeLabel: Record<FindingType, string> = {
  regression: '回归缺陷',
  'spec-mismatch': '需求偏差',
  contract: '契约异常',
  duplicate: '疑似重复',
  flaky: '不稳定',
}

export const verdictLabel: Record<Verdict, string> = {
  confirm: '已确认',
  reject: '已驳回',
  'false-positive': '误报',
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

export function formatFullTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`
}

export function formatDuration(ms: number): string {
  if (!ms) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function logLevel(line: string): 'error' | 'warn' | 'info' {
  if (/\bERROR\b|\bFAILED\b|Traceback/.test(line)) return 'error'
  if (/\bWARN\b|\bskip\b/i.test(line)) return 'warn'
  return 'info'
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      return true
    } catch {
      return false
    }
  }
}
