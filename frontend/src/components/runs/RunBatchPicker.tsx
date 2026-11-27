import { useEffect, useMemo, useRef, useState } from 'react'
import type { Run } from '../../types'
import { Icon } from '../ui'

interface Props {
  runs: Run[]
  activeRunId: string
  pendingByRun: Map<string, number>
  onSelect: (runId: string) => void
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function timeLabel(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--:--'
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function dateGroupLabel(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '未知日期'
  const now = new Date()
  const today = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime()
  const target = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  ).getTime()
  const diffDays = Math.round((today - target) / 86400000)
  if (diffDays === 0) return '今天'
  if (diffDays === 1) return '昨天'
  if (date.getFullYear() === now.getFullYear()) {
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function shortRunId(id: string): string {
  const tail = id.split('-').pop() ?? id
  return tail.length > 8 ? tail.slice(-8) : tail
}

function runTone(
  run: Run,
  pending: number,
): 'success' | 'warning' | 'danger' {
  if (run.stats.failed + run.stats.error > 0) return 'danger'
  if (pending > 0) return 'warning'
  return 'success'
}

function refLabel(run: Run): string {
  const ref = [run.branch, run.commit ? run.commit.slice(0, 7) : '']
    .filter(Boolean)
    .join(' @ ')
  return ref || run.environment || '—'
}

export function RunBatchPicker({
  runs,
  activeRunId,
  pendingByRun,
  onSelect,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  const activeRun =
    runs.find((item) => item.id === activeRunId) ?? runs[0]
  const activePending = activeRun
    ? pendingByRun.get(activeRun.id) ?? 0
    : 0

  useEffect(() => {
    if (!open) return
    setQuery('')
    searchRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', handlePointer)
    return () => document.removeEventListener('pointerdown', handlePointer)
  }, [open])

  const groups = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    const visible = keyword
      ? runs.filter((item) =>
          `${item.id} ${item.branch} ${item.commit} ${item.environment} ${item.startedAt}`
            .toLowerCase()
            .includes(keyword),
        )
      : runs
    const grouped = new Map<string, Run[]>()
    for (const item of visible) {
      const label = dateGroupLabel(item.startedAt)
      const bucket = grouped.get(label)
      if (bucket) bucket.push(item)
      else grouped.set(label, [item])
    }
    return Array.from(grouped, ([label, items]) => ({ label, items }))
  }, [query, runs])

  if (!activeRun) return null

  const tone = runTone(activeRun, activePending)

  return (
    <div className="run-batch-picker" ref={rootRef}>
      <button
        type="button"
        className="run-batch-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="选择运行批次"
        title={activeRun.id}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="run-batch-trigger-main">
          <span className={`run-batch-dot is-${tone}`} />
          <span className="run-batch-trigger-label">
            {`${dateGroupLabel(activeRun.startedAt)} ${timeLabel(
              activeRun.startedAt,
            )} · ${shortRunId(activeRun.id)}`}
          </span>
          {activePending > 0 && (
            <span className="run-batch-pending">{activePending} 待审判</span>
          )}
        </span>
        <Icon
          name="chevronDown"
          size={14}
          className={open ? 'is-open' : undefined}
        />
      </button>

      {open && (
        <div
          className="run-batch-popover"
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpen(false)
          }}
        >
          <label className="run-batch-search">
            <Icon name="search" size={13} />
            <input
              ref={searchRef}
              value={query}
              placeholder="搜索批次 ID / commit / 分支"
              aria-label="搜索运行批次"
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') setOpen(false)
              }}
            />
          </label>

          <div className="run-batch-list" role="listbox" aria-label="运行批次">
            {groups.map((group) => (
              <div
                className="run-batch-group"
                key={group.label}
                role="group"
                aria-label={group.label}
              >
                <div className="run-batch-group-label">{group.label}</div>
                {group.items.map((item) => {
                  const isActive = item.id === activeRunId
                  const pending = pendingByRun.get(item.id) ?? 0
                  const { failed, error, skipped, passed } = item.stats
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={isActive}
                      className={`run-batch-row ${isActive ? 'is-active' : ''}`}
                      title={item.id}
                      onClick={() => {
                        onSelect(item.id)
                        setOpen(false)
                      }}
                    >
                      <span className="run-batch-row-top">
                        <span className="run-batch-row-id">
                          <span className="run-batch-row-time">
                            {timeLabel(item.startedAt)}
                          </span>
                          <span className="run-batch-row-hash">
                            {shortRunId(item.id)}
                          </span>
                          {isActive && (
                            <Icon
                              name="check"
                              size={12}
                              className="run-batch-check"
                            />
                          )}
                        </span>
                        {pending > 0 && (
                          <span className="run-batch-pending">
                            {pending} 待审判
                          </span>
                        )}
                      </span>
                      <span className="run-batch-row-bottom">
                        <span className="run-batch-row-ref">
                          {refLabel(item)}
                        </span>
                        <span className="run-batch-row-stats">
                          {failed + error > 0 ? (
                            <>
                              {failed > 0 && (
                                <em className="is-danger">{failed} 失败</em>
                              )}
                              {error > 0 && (
                                <em className="is-danger">{error} 错误</em>
                              )}
                            </>
                          ) : (
                            <em className="is-success">通过 {passed}</em>
                          )}
                          {skipped > 0 && <em>{skipped} 跳过</em>}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            ))}
            {groups.length === 0 && (
              <div className="run-batch-empty">没有匹配的批次</div>
            )}
          </div>

          <div className="run-batch-foot">
            {query.trim()
              ? `${groups.reduce(
                  (sum, group) => sum + group.items.length,
                  0,
                )} / ${runs.length} 个批次`
              : `共 ${runs.length} 个批次`}
          </div>
        </div>
      )}
    </div>
  )
}
