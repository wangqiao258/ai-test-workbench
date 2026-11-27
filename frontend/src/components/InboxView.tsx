import { useMemo, useState } from 'react'
import type {
  AppData,
  Finding,
  FindingType,
  Navigate,
  Severity,
} from '../types'
import {
  findingTypeLabel,
  formatDateTime,
  severityLabel,
  severityRank,
} from '../utils/format'
import {
  Confidence,
  EmptyState,
  FindingTypeBadge,
  Icon,
  SeverityBadge,
} from './ui'

interface Props {
  data: AppData
  navigate: Navigate
}

const SEVERITIES: Severity[] = ['blocker', 'critical', 'major', 'minor']
const FINDING_TYPES: FindingType[] = [
  'regression',
  'spec-mismatch',
  'contract',
  'duplicate',
  'flaky',
]

export function InboxView({ data, navigate }: Props) {
  const [severity, setSeverity] = useState<'all' | Severity>('all')
  const [type, setType] = useState<'all' | FindingType>('all')
  const [runFilter, setRunFilter] = useState('all')
  const [keyword, setKeyword] = useState('')

  const pending = useMemo(
    () => data.findings.filter((item) => item.status === 'pending'),
    [data.findings],
  )

  const pendingByRun = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of pending) {
      counts.set(item.runId, (counts.get(item.runId) ?? 0) + 1)
    }
    return counts
  }, [pending])

  const runsWithPending = useMemo(
    () => data.runs.filter((run) => pendingByRun.has(run.id)),
    [data.runs, pendingByRun],
  )

  const filtered = useMemo(() => {
    const lower = keyword.trim().toLowerCase()
    return pending
      .filter(
        (item) => severity === 'all' || item.suggestedSeverity === severity,
      )
      .filter((item) => type === 'all' || item.type === type)
      .filter((item) => runFilter === 'all' || item.runId === runFilter)
      .filter((item) => {
        if (!lower) return true
        return `${item.id} ${item.title} ${item.summary} ${item.nodeid}`
          .toLowerCase()
          .includes(lower)
      })
      .sort(
        (left, right) =>
          severityRank[left.suggestedSeverity] -
            severityRank[right.suggestedSeverity] ||
          right.createdAt.localeCompare(left.createdAt),
      )
  }, [keyword, pending, runFilter, severity, type])

  const openFinding = (finding: Finding) => {
    navigate({
      module: 'runs',
      runId: finding.runId,
      evidenceNodeid: finding.nodeid,
      exchangeIndex: finding.exchangeIndex ?? 0,
      findingId: finding.id,
    })
  }

  return (
    <div className="view">
      <header className="view-head">
        <div>
          <h1 className="view-title">待审判</h1>
          <p className="view-desc">
            跨批次汇总 AI 发现，裁决后自动跳到下一条。
          </p>
        </div>
        <div className="head-tags">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!filtered.length}
            onClick={() => {
              if (filtered[0]) openFinding(filtered[0])
            }}
          >
            开始审判
          </button>
        </div>
      </header>

      <div className="view-body">
        <div className="table-card">
          <div className="table-toolbar">
            <label className="search-field">
              <Icon name="search" size={14} />
              <input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索标题、根因、用例 nodeid"
                aria-label="搜索待审判发现"
              />
            </label>
            <select
              className="select"
              value={severity}
              onChange={(event) =>
                setSeverity(event.target.value as 'all' | Severity)
              }
              aria-label="按严重度筛选"
            >
              <option value="all">全部严重度</option>
              {SEVERITIES.map((item) => (
                <option key={item} value={item}>
                  {severityLabel[item]}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={type}
              onChange={(event) =>
                setType(event.target.value as 'all' | FindingType)
              }
              aria-label="按类型筛选"
            >
              <option value="all">全部类型</option>
              {FINDING_TYPES.map((item) => (
                <option key={item} value={item}>
                  {findingTypeLabel[item]}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={runFilter}
              onChange={(event) => setRunFilter(event.target.value)}
              aria-label="按批次筛选"
            >
              <option value="all">全部批次</option>
              {runsWithPending.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.id} · {pendingByRun.get(run.id)} 条
                </option>
              ))}
            </select>
            <div className="toolbar-spacer" />
            <span className="result-count">{filtered.length} 条</span>
          </div>

          <div className="table-scroll">
            {filtered.length ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '9%' }}>严重度</th>
                    <th style={{ width: '36%' }}>AI 发现</th>
                    <th style={{ width: '23%' }}>用例</th>
                    <th style={{ width: '20%' }}>批次</th>
                    <th style={{ width: '10%' }}>置信度</th>
                    <th style={{ width: '2%' }} />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((finding) => {
                    const run = data.runs.find(
                      (item) => item.id === finding.runId,
                    )
                    const testCase = data.cases.find(
                      (item) => item.nodeid === finding.nodeid,
                    )
                    return (
                      <tr
                        key={finding.id}
                        className="is-clickable"
                        onClick={() => openFinding(finding)}
                      >
                        <td>
                          <SeverityBadge
                            severity={finding.suggestedSeverity}
                          />
                        </td>
                        <td>
                          <div className="case-name">{finding.title}</div>
                          <div className="case-row-meta">
                            <FindingTypeBadge type={finding.type} />
                            <code className="case-nodeid">{finding.id}</code>
                          </div>
                        </td>
                        <td>
                          <div className="case-name">
                            {testCase?.name ??
                              finding.nodeid.split('::')[1] ??
                              finding.nodeid}
                          </div>
                          <code className="case-nodeid">{finding.nodeid}</code>
                        </td>
                        <td>
                          <div className="status-stack">
                            <code>{finding.runId}</code>
                            <span className="cell-sub">
                              {formatDateTime(
                                run?.startedAt ?? finding.createdAt,
                              )}
                            </span>
                          </div>
                        </td>
                        <td>
                          <Confidence value={finding.confidence} />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="icon-btn table-action"
                            aria-label="查看证据并审判"
                            onClick={(event) => {
                              event.stopPropagation()
                              openFinding(finding)
                            }}
                          >
                            <Icon name="arrowRight" size={14} />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <EmptyState
                icon={pending.length ? 'filter' : 'check'}
                title={
                  pending.length ? '没有匹配的发现' : '待审判已清空'
                }
                description={
                  pending.length
                    ? '调整严重度、类型、批次或关键字后再试。'
                    : 'AI 机上传新的分析结果后，待审判发现会出现在这里。'
                }
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
