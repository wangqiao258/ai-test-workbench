import { useEffect, useState, type ReactNode } from 'react'
import type {
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
import { formatDateTime, formatDuration } from '../utils/format'
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
        <div className="view-kicker">RUN TRIAL / 03</div>
        <h1 className="view-title">运行与审判</h1>
        <p className="view-desc">
          pytest 结果、HAR 证据与人工裁决集中在一处；AI
          分析由外部流水线落库，平台只负责聚合与裁决。
        </p>
      </div>
      <div className="head-tags">
        <span className="head-tag">
          <Icon name="server" size={13} />
          pytest
        </span>
        <span className="head-tag">
          <Icon name="file" size={13} />
          HAR 证据
        </span>
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
  const pendingCount = runFindings.filter(
    (item) => item.status === 'pending',
  ).length

  const visibleCases = onlyFailed
    ? run.cases.filter(
        (item) => item.status === 'failed' || item.status === 'error',
      )
    : run.cases

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
    const matchedFinding =
      data.findings.find(
        (item) =>
          item.runId === run.id &&
          item.nodeid === nodeid &&
          item.status === 'pending',
      ) ??
      data.findings.find(
        (item) => item.runId === run.id && item.nodeid === nodeid,
      )
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
                {data.runs.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} · {formatDateTime(item.startedAt)}
                  </option>
                ))}
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
                return (
                  <button
                    key={item.nodeid}
                    type="button"
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

          <div className="pane-left-foot">
            <span className="mono-id">{run.environment}</span>
          </div>
        </aside>

        <EvidencePanel
          data={data}
          nav={nav}
          navigate={navigate}
          runCase={activeRunCase}
          testCase={testCase}
          pendingCount={pendingCount}
          loading={!detail}
          onOpenTrial={() => setTrialOpen(true)}
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
          data={data}
          nav={nav}
          navigate={navigate}
          summary={data.summaries[run.id]}
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