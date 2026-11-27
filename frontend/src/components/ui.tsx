import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type {
  FindingType,
  HttpMethod,
  RunStatus,
  Severity,
  ToastTone,
  Verdict,
} from '../types'
import {
  copyText,
  findingTypeLabel,
  runStatusLabel,
  severityLabel,
  verdictLabel,
} from '../utils/format'

const iconPaths = {
  book: (
    <>
      <path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H19v20H7.5A2.5 2.5 0 0 1 5 19.5z" />
      <path d="M5 17.5h14M8.5 6h6M8.5 10h4" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </>
  ),
  play: <path d="M8 5.5v13l11-6.5z" />,
  bug: (
    <>
      <rect x="7" y="7" width="10" height="12" rx="5" />
      <path d="M12 7V4M8.5 4.5 7 3M15.5 4.5 17 3M7 11H3M7 15H4M17 11h4M17 15h3M9 19l-1.5 2M15 19l1.5 2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  chevronDown: <path d="m6 9 6 6 6-6" />,
  chevronRight: <path d="m9 6 6 6-6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  alert: (
    <>
      <path d="M12 3 2.8 20h18.4L12 3Z" />
      <path d="M12 9v4.5M12 17h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 4v7h-7" />
    </>
  ),
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  arrowLeft: <path d="M19 12H5M11 6l-6 6 6 6" />,
  external: (
    <>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </>
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7-7.1L10.8 5.3" />
      <path d="M14 11a5 5 0 0 0-7.1-.1l-2 2a5 5 0 0 0 7 7.1l1.3-1.3" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  branch: (
    <>
      <circle cx="6" cy="6" r="2" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="8" r="2" />
      <path d="M6 8v8M18 10c0 4-4 4-8 5" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 7.5h.01M7 16.5h.01" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </>
  ),
  terminal: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="m7 9 3 3-3 3M13 15h4" />
    </>
  ),
  spark: (
    <path d="M12 2c.6 5.2 4.2 8.8 9.4 9.4-5.2.6-8.8 4.2-9.4 9.4-.6-5.2-4.2-8.8-9.4-9.4C7.8 10.8 11.4 7.2 12 2Z" />
  ),
  shield: (
    <>
      <path d="M12 3 5 6v5c0 4 3 7.5 7 9 4-1.5 7-5 7-9V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  panelLeft: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
    </>
  ),
  filter: <path d="M4 6h16M7 12h10M10 18h4" />,
  arrowRight: <path d="M5 12h14M13 6l6 6-6 6" />,
}

export type IconName = keyof typeof iconPaths

export function Icon({
  name,
  size = 16,
  className,
}: {
  name: IconName
  size?: number
  className?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {iconPaths[name]}
    </svg>
  )
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`severity severity-${severity}`}>
      <i />
      {severityLabel[severity]}
    </span>
  )
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`run-status run-status-${status}`}>
      <i />
      {runStatusLabel[status]}
    </span>
  )
}

export function MethodTag({ method }: { method: HttpMethod }) {
  return <span className={`method method-${method.toLowerCase()}`}>{method}</span>
}

export function FindingTypeBadge({ type }: { type: FindingType }) {
  return <span className={`finding-type finding-type-${type}`}>{findingTypeLabel[type]}</span>
}

export function VerdictStamp({ verdict }: { verdict: Verdict }) {
  const icon: IconName =
    verdict === 'confirm' ? 'check' : verdict === 'reject' ? 'x' : 'alert'
  return (
    <span className={`verdict-stamp verdict-${verdict}`}>
      <Icon name={icon} size={12} />
      {verdictLabel[verdict]}
    </span>
  )
}

export function Confidence({ value }: { value: number }) {
  const width = Math.round(value * 100)
  return (
    <span className="confidence" title="AI 置信度">
      <span className="confidence-track">
        <span style={{ width: `${width}%` }} />
      </span>
      {width}%
    </span>
  )
}

interface SegmentedOption<T extends string> {
  value: T
  label: string
  count?: number
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
}: {
  options: SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div className={`segmented segmented-${size}`} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={`segmented-item ${value === option.value ? 'is-active' : ''}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {typeof option.count === 'number' && (
            <span className="segmented-count">{option.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}

export function CopyButton({
  text,
  onCopied,
  label = '复制',
}: {
  text: string
  onCopied?: () => void
  label?: string
}) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(timer)
  }, [copied])

  return (
    <button
      type="button"
      className="btn btn-ghost btn-xs"
      onClick={async () => {
        const ok = await copyText(text)
        if (ok) {
          setCopied(true)
          onCopied?.()
        }
      }}
    >
      <Icon name={copied ? 'check' : 'copy'} size={13} />
      {copied ? '已复制' : label}
    </button>
  )
}

export function EmptyState({
  icon = 'layers',
  title,
  description,
  action,
}: {
  icon?: IconName
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name={icon} size={22} />
      </span>
      <strong>{title}</strong>
      {description && <p>{description}</p>}
      {action}
    </div>
  )
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="skeleton-list" aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="skeleton-row" key={index}>
          <span className="skeleton skeleton-dot" />
          <div>
            <span className="skeleton skeleton-line" style={{ width: `${58 + index * 7}%` }} />
            <span className="skeleton skeleton-line skeleton-line-sm" style={{ width: `${36 + index * 4}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function Toast({
  text,
  tone,
}: {
  text: string
  tone: ToastTone
}) {
  return (
    <div className={`toast toast-${tone}`} role="status">
      <span className="toast-icon">
        <Icon
          name={tone === 'success' ? 'check' : tone === 'danger' ? 'alert' : 'info'}
          size={14}
        />
      </span>
      {text}
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  description: string
  confirmText: string
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!open) return null
  return (
    <div className="dialog-backdrop" onMouseDown={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon">
            <Icon name="refresh" size={18} />
          </span>
          <div>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel}>
            取消
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}

export function DialogShell({
  open,
  title,
  description,
  icon = 'plus',
  wide = false,
  className = '',
  busy = false,
  busyText = '提交中…',
  error = '',
  submitText,
  canSubmit = true,
  onCancel,
  onSubmit,
  footer,
  children,
}: {
  open: boolean
  title: string
  description: string
  icon?: IconName
  wide?: boolean
  className?: string
  busy?: boolean
  busyText?: string
  error?: string
  submitText: string
  canSubmit?: boolean
  onCancel: () => void
  onSubmit?: () => void
  footer?: ReactNode
  children: ReactNode
}) {
  if (!open) return null
  return (
    <div className="dialog-backdrop" onMouseDown={busy ? undefined : onCancel}>
      <form
        className={`dialog ${wide ? 'dialog-wide' : ''} ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault()
          if (!busy && canSubmit) onSubmit?.()
        }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-primary">
            <Icon name={icon} size={18} />
          </span>
          <div>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
        </div>
        {children}
        {error && <p className="dialog-error">{error}</p>}
        {footer ?? (
          <div className="dialog-actions">
            <button type="button" className="btn" onClick={onCancel} disabled={busy}>
              取消
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !canSubmit}
            >
              {busy ? busyText : submitText}
            </button>
          </div>
        )}
      </form>
    </div>
  )
}
