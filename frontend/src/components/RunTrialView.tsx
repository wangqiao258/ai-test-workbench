import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type {
  AiSummary,
  AppData,
  Defect,
  Finding,
  Navigate,
  NavState,
  RunCase,
  RunStatus,
  ToastTone,
  Verdict,
} from '../types'
import { api } from '../services/api'
import { formatDateTime, formatDuration, severityRank } from '../utils/format'
import { EvidencePanel } from './EvidencePanel'
import { FindingsPanel } from './FindingsPanel'
import { EmptyState, Icon } from './ui'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  onJudge: (
    id: string,
    verdict: Verdict,
    note: string,
  ) => Promise<{ finding: Finding; defect?: Defect }>
  onToast: (text: string, tone?: ToastTone) => void
}

const STAT_ITEMS: Array<{ key: RunStatus; label: string }> = [
  { key: 'passed', label: '通过' },
  { key: 'failed', label: '失败' },
  { key: 'error', label: '错误' },
  { key: 'skipped', label: '跳过' },
]

function RunHeader() {
  return (
    <header className="view-head">
      <div>
        <div className="view-kicker">RUN EVIDENCE / 04</div>
        <h1 className="view-title">运行证据</h1>
        <p className="view-desc">
          按批次查看 pytest 结果与 HAR 证据；待裁决的 AI
          发现已集中到「待审判」收件箱。
        </p>
      </div>
    </header>
  )
}

function RunEmpty({
  header,
  title,
  description,
}: {
  header: ReactNode
  title: string
  description: string
}) {
  return (
    <div className="view">
      {header}
      <div className="view-body">
        <EmptyState icon="play" title={title} description={description} />
      </div>
    </div>
  )
}

export function RunTrialView({
  data,
  nav,
  navigate,
  onJudge,
  onToast,
}: Props) {
  const [onlyFailed, setOnlyFailed] = useState(false)
  const [trialOpen, setTrialOpen] = useState(false)
  const [caseDetails, setCaseDetails] = useState<Record<string, RunCase>>({})
  const [summary, setSummary] = useState<AiSummary | undefined>(undefined)

  const header = <RunHeader />

  const run = data.runs.find((item) => item.id === nav.runId) ?? data.runs[0]
  const runCase = run
    ? run.cases.find((item) => item.nodeid === nav.evidenceNodeid) ??
      run.cases[0]
    : undefined
  const detailKey = run && runCase ? `${run.id}::${runCase.nodeid}` : ''
  const detail = detailKey ? caseDetails[detailKey] : undefined

  useEffect(() => {
    if (!run || !runCase || !detailKey || caseDetails[detailKey]) return
    const projectId = nav.projectId
    const { id: runId } = run
    const { nodeid } = runCase
    let alive = true
    api
      .fetchRunCaseDetail(projectId, runId, nodeid)
      .then((item) => {
        if (!alive) return
        setCaseDetails((prev) => ({ ...prev, [detailKey]: item }))
      })
      .catch(() => {
        if (!alive) return
        setCaseDetails((prev) => ({ ...prev, [detailKey]: runCase }))
      })
    return () => {
      alive = false
    }
  }, [caseDetails, detailKey, nav.projectId, run, runCase])

  useEffect(() => {
    if (!run) return
    if (data.summaries[run.id]) {
      setSummary(data.summaries[run.id])
      return
    }
    const projectId = nav.projectId
    const runId = run.id
    let alive = true
    setSummary(undefined)
    api
      .fetchRunAnalysis(projectId, runId)
      .then((item) => {
        if (alive) setSummary(item)
      })
      .catch(() => {
        if (alive) setSummary(undefined)
      })
    return () => {
      alive = false
    }
  }, [data.summaries, nav.projectId, run])

  const pendingByRun = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of data.findings) {
      if (item.status !== 'pending') continue
      counts.set(item.runId, (counts.get(item.runId) ?? 0) + 1)
    }
    return counts
  }, [data.findings])

  const findingCounts = useMemo(() => {
    const counts = new Map<string, { total: number; pending: number }>()
    if (!run) return counts
    for (const item of data.findings) {
      if (item.runId !== run.id) continue
      const current = counts.get(item.nodeid) ?? { total: 0, pending: 0 }
      current.total += 1
      if (item.status === 'pending') current.pending += 1
      counts.set(item.nodeid, current)
    }
    return counts
  }, [data.findings, run])

  const activeCaseRef = useRef<HTMLButtonElement | null>(null)
  const lastNodeidRef = useRef('')

  useEffect(() => {
    activeCaseRef.current?.scrollIntoView({ block: 'nearest' })
  }, [onlyFailed, run?.id, runCase?.nodeid])

  useEffect(() => {
    const nodeid = runCase?.nodeid ?? ''
    if (nodeid === lastNodeidRef.current) return
    lastNodeidRef.current = nodeid
    if (
      onlyFailed &&
      runCase &&
      runCase.status !== 'failed' &&
      runCase.status !== 'error'
    ) {
      setOnlyFailed(false)
    }
  }, [onlyFailed, runCase])

  if (!run) {
    return (
      <RunEmpty
        header={header}
        title="还没有运行批次"
        description="AI 执行 pytest 并通过插件上传结果后，这里会显示批次、用例与证据。"
      />
    )
  }
  if (!runCase) {
    return (
      <RunEmpty
        header={header}
        title="本次运行没有用例"
        description="重新上传运行结果后再查看证据与 AI 发现。"
      />
    )
  }
  const activeRunCase = detail ?? runCase
  const testCase = data.cases.find((item) => item.nodeid === runCase.nodeid)
  const runFindings = data.findings.filter((item) => item.runId === run.id)
  const caseFindings = runFindings.filter(
    (item) => item.nodeid === runCase.nodeid,
  )
  const pendingCount = caseFindings.filter(
    (item) => item.status === 'pending',
  ).length

  const visibleCases = onlyFailed
    ? run.cases.filter(
        (item) => item.status === 'failed' || item.status === 'error',
      )
    : run.cases

  const openTrial = () => {
    const casePending = data.findings.filter(
      (item) =>
        item.runId === run.id &&
        item.nodeid === runCase.nodeid &&
        item.status === 'pending',
    )
    const target =
      casePending.find((item) => item.id === nav.findingId) ??
      casePending.sort(
        (left, right) =>
          severityRank[left.suggestedSeverity] -
            severityRank[right.suggestedSeverity] ||
          right.createdAt.localeCompare(left.createdAt),
      )[0]
    if (target && target.id !== nav.findingId) {
      navigate({
        findingId: target.id,
        exchangeIndex: target.exchangeIndex ?? 0,
      })
    }
    setTrialOpen(true)
  }

  const selectRun = (runId: string) => {
    const nextRun = data.runs.find((item) => item.id === runId)
    if (!nextRun) return
    const nextPending = data.findings.find(
      (item) => item.runId === runId && item.status === 'pending',
    )
    const fallbackCase =
      nextRun.cases.find(
        (item) => item.status === 'failed' || item.status === 'error',
      ) ?? nextRun.cases[0]
    const targetNodeid = nextPending?.nodeid ?? fallbackCase?.nodeid ?? ''
    navigate({
      runId,
      evidenceNodeid: targetNodeid,
      exchangeIndex: nextPending?.exchangeIndex ?? 0,
      findingId: nextPending?.id ?? '',
    })
  }

  const selectCase = (nodeid: string) => {
    const matchedFinding = data.findings
      .filter((item) => item.runId === run.id && item.nodeid === nodeid)
      .sort(
        (left, right) =>
          (left.status === 'pending' ? 0 : 1) -
            (right.status === 'pending' ? 0 : 1) ||
          severityRank[left.suggestedSeverity] -
            severityRank[right.suggestedSeverity],
      )[0]
    navigate({
      evidenceNodeid: nodeid,
      exchangeIndex: matchedFinding?.exchangeIndex ?? 0,
      findingId: matchedFinding?.id ?? '',
    })
  }

  return (
    <div className="view">
      {header}

      <div className="workspace-wrap">
        <div className="workspace">
        <aside className="pane pane-left">
          <div className="run-switcher">
            <label className="run-select-label" htmlFor="run-select">
              RUN BATCH
            </label>
            <div className="run-select-wrap">
              <select
                id="run-select"
                className="run-select"
                value={run.id}
                onChange={(event) => selectRun(event.target.value)}
              >
                {data.runs.map((item) => {
                  const pending = pendingByRun.get(item.id) ?? 0
                  return (
                    <option key={item.id} value={item.id}>
                      {item.id} · {formatDateTime(item.startedAt)}
                      {pending > 0 ? ` · ${pending} 待审判` : ''}
                    </option>
                  )
                })}
              </select>
              <Icon name="chevronDown" size={14} />
            </div>
            <div className="run-meta-line">
              <span>
                <Icon name="clock" size={12} />
                {formatDateTime(run.startedAt)} · {formatDuration(run.durationMs)}
              </span>
              <span>
                <Icon name="branch" size={12} />
                {run.branch}
                <code>{run.commit}</code>
              </span>
            </div>
            <div className="run-stats">
              {STAT_ITEMS.map((item) => (
                <div
                  key={item.key}
                  className={`run-stat run-stat-${item.key}`}
                >
                  <b>{run.stats[item.key]}</b>
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="case-list-head">
            <div className="case-list-title">
              用例
              <span className="count-pill">{visibleCases.length}</span>
            </div>
            <label className="switch">
              <input
                type="checkbox"
                checked={onlyFailed}
                onChange={(event) => setOnlyFailed(event.target.checked)}
              />
              <span className="switch-track" />
              仅看失败
            </label>
          </div>

          <div className="case-list">
            {visibleCases.length ? (
              visibleCases.map((item) => {
                const meta = data.cases.find(
                  (test) => test.nodeid === item.nodeid,
                )
                const active = item.nodeid === runCase.nodeid
                const findingCount = findingCounts.get(item.nodeid)
                return (
                  <button
                    key={item.nodeid}
                    type="button"
                    ref={active ? activeCaseRef : undefined}
                    className={`case-row ${active ? 'is-active' : ''}`}
                    onClick={() => selectCase(item.nodeid)}
                  >
                    <span className={`case-dot case-dot-${item.status}`} />
                    <div className="case-row-main">
                      <div className="case-row-name">
                        {meta?.name ?? item.nodeid.split('::')[1]}
                      </div>
                      <div className="case-row-meta">
                        <span>{item.nodeid.split('::')[0]}</span>
                        {findingCount && (
                          <span
                            className={`case-row-finding ${
                              findingCount.pending > 0 ? 'is-pending' : ''
                            }`}
                            title={`本用例 ${findingCount.total} 条 AI 发现，${findingCount.pending} 条待审判`}
                          >
                            <Icon name="spark" size={11} />
                            {findingCount.pending > 0
                              ? `${findingCount.pending} 待审判`
                              : `${findingCount.total} 条发现`}
                          </span>
                        )}
                        {item.error && (
                          <span className="case-row-error">
                            <Icon name="alert" size={11} />
                            失败
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="case-row-time">
                      {formatDuration(item.durationMs)}
                    </span>
                  </button>
                )
              })
            ) : (
              <div className="case-list-empty">当前批次没有失败用例。</div>
            )}
          </div>

          {run.environment && (
            <div className="pane-left-foot">
              <span className="mono-id">{run.environment}</span>
            </div>
          )}
        </aside>

        <EvidencePanel
          data={data}
          nav={nav}
          navigate={navigate}
          runId={run.id}
          runCase={activeRunCase}
          testCase={testCase}
          pendingCount={pendingCount}
          loading={!detail}
          onOpenTrial={openTrial}
          onToast={onToast}
        />

        {trialOpen && (
          <div
            className="trial-scrim"
            onClick={() => setTrialOpen(false)}
            aria-hidden="true"
          />
        )}

        <FindingsPanel
          run={run}
          nodeid={runCase.nodeid}
          data={data}
          nav={nav}
          navigate={navigate}
          summary={summary}
          onJudge={onJudge}
          onToast={onToast}
          open={trialOpen}
          onClose={() => setTrialOpen(false)}
        />
        </div>
      </div>
    </div>
  )
}