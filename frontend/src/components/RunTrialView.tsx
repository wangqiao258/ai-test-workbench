import { useEffect, useState, type ReactNode } from 'react'
import type {
  AppData,
  Defect,
  Finding,
  Navigate,
  NavState,
  RunRequest,
  RunRequestStatus,
  RunStatus,
  ToastTone,
  Verdict,
} from '../types'
import { api, API_MODE, type CreateRunRequestInput } from '../services/api'
import { formatDateTime, formatDuration } from '../utils/format'
import { EvidencePanel } from './EvidencePanel'
import { FindingsPanel } from './FindingsPanel'
import { RunRequestDialog } from './RunRequestDialog'
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
  onRefresh: () => Promise<void>
}

const STAT_ITEMS: Array<{ key: RunStatus; label: string }> = [
  { key: 'passed', label: '通过' },
  { key: 'failed', label: '失败' },
  { key: 'error', label: '错误' },
  { key: 'skipped', label: '跳过' },
]

const REQUEST_STATUS_LABEL: Record<RunRequestStatus, string> = {
  queued: '排队中',
  running: '执行中',
  succeeded: '运行完成',
  failed: '运行失败',
  canceled: '已取消',
}

function RunHeader({
  request,
  onOpen,
}: {
  request: RunRequest | null
  onOpen: () => void
}) {
  const busy = request?.status === 'queued' || request?.status === 'running'
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
        {request && (
          <span className="head-tag" title={request.error ?? undefined}>
            {REQUEST_STATUS_LABEL[request.status]}
            {request.runExternalId ? ` · ${request.runExternalId}` : ''}
          </span>
        )}
        {API_MODE === 'http' && (
          <button
            type="button"
            className="btn btn-primary btn-xs"
            disabled={busy}
            onClick={onOpen}
          >
            <Icon name="play" size={12} />
            {busy ? '执行中…' : '运行测试'}
          </button>
        )}
      </div>
    </header>
  )
}

function RunEmpty({
  header,
  dialog,
  title,
  description,
}: {
  header: ReactNode
  dialog: ReactNode
  title: string
  description: string
}) {
  return (
    <div className="view">
      {header}
      <div className="view-body">
        <EmptyState icon="play" title={title} description={description} />
      </div>
      {dialog}
    </div>
  )
}

export function RunTrialView({
  data,
  nav,
  navigate,
  onJudge,
  onToast,
  onRefresh,
}: Props) {
  const [onlyFailed, setOnlyFailed] = useState(false)
  const [trialOpen, setTrialOpen] = useState(false)
  const [requestOpen, setRequestOpen] = useState(false)
  const [request, setRequest] = useState<RunRequest | null>(null)

  const projectId = nav.projectId
  const requestId = request?.id
  const requestStatus = request?.status

  useEffect(() => {
    let alive = true
    setRequest(null)
    api
      .listRunRequests(projectId)
      .then((items) => {
        if (!alive) return
        const active = items.find(
          (item) => item.status === 'queued' || item.status === 'running',
        )
        if (active) setRequest(active)
      })
      .catch(() => {
        // 运行任务列表不可用时不影响运行结果展示。
      })
    return () => {
      alive = false
    }
  }, [projectId])

  useEffect(() => {
    if (
      !requestId ||
      (requestStatus !== 'queued' && requestStatus !== 'running')
    ) {
      return
    }
    let alive = true
    const timer = window.setInterval(() => {
      api
        .fetchRunRequest(projectId, requestId)
        .then(async (next) => {
          if (!alive) return
          setRequest(next)
          if (next.status === 'queued' || next.status === 'running') return
          window.clearInterval(timer)
          if (next.status === 'succeeded') {
            onToast(
              next.runExternalId
                ? `运行完成：${next.runExternalId}`
                : '运行完成',
              'success',
            )
          } else {
            const detail = next.error?.split('\n')[0] ?? ''
            onToast(`运行失败${detail ? `：${detail}` : ''}`, 'danger')
          }
          await onRefresh()
        })
        .catch(() => {
          // 单次轮询失败不终止，等待下一次。
        })
    }, 3000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [projectId, requestId, requestStatus, onToast, onRefresh])

  const submitRequest = async (input: CreateRunRequestInput) => {
    const created = await api.createRunRequest(projectId, input)
    setRequest(created)
    setRequestOpen(false)
    onToast('运行任务已创建，等待 Runner 执行', 'info')
  }

  const header = (
    <RunHeader request={request} onOpen={() => setRequestOpen(true)} />
  )

  const requestDialog = (
    <RunRequestDialog
      open={requestOpen}
      onCancel={() => setRequestOpen(false)}
      onSubmit={submitRequest}
    />
  )

  const run = data.runs.find((item) => item.id === nav.runId) ?? data.runs[0]
  if (!run) {
    return (
      <RunEmpty
        header={header}
        dialog={requestDialog}
        title="还没有运行批次"
        description="点击「运行测试」创建任务，Runner 执行后这里会显示批次、用例与证据。"
      />
    )
  }
  const runCase =
    run.cases.find((item) => item.nodeid === nav.evidenceNodeid) ?? run.cases[0]
  if (!runCase) {
    return (
      <RunEmpty
        header={header}
        dialog={requestDialog}
        title="本次运行没有用例"
        description="重新上传运行结果后再查看证据与 AI 发现。"
      />
    )
  }
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
    const targetNodeid = nextPending?.nodeid ?? fallbackCase.nodeid
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
            <span>捕捉器 pytest-traffic-capture</span>
          </div>
        </aside>

        <EvidencePanel
          data={data}
          nav={nav}
          navigate={navigate}
          runCase={runCase}
          testCase={testCase}
          pendingCount={pendingCount}
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

      {requestDialog}
    </div>
  )
}