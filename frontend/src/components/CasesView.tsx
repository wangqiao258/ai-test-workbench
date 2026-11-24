import { useMemo, useState } from 'react'
import type {
  AppData,
  Navigate,
  NavState,
  RunStatus,
  TestCase,
} from '../types'
import {
  formatDateTime,
  formatDuration,
  percent,
} from '../utils/format'
import {
  EmptyState,
  Icon,
  MethodTag,
  RunStatusBadge,
  type IconName,
} from './ui'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
}

const STATUS_OPTIONS: Array<{ value: 'all' | RunStatus; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'passed', label: '通过' },
  { value: 'failed', label: '失败' },
  { value: 'error', label: '错误' },
  { value: 'skipped', label: '跳过' },
]

function StatCard({
  label,
  value,
  hint,
  progress,
  icon,
}: {
  label: string
  value: string
  hint: string
  progress?: number
  icon: IconName
}) {
  return (
    <div className="stat-card">
      <div className="stat-card-head">
        <span>{label}</span>
        <span className="stat-icon">
          <Icon name={icon} size={15} />
        </span>
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint">{hint}</div>
      {typeof progress === 'number' && (
        <div className="stat-track" aria-hidden="true">
          <span style={{ width: percent(progress) }} />
        </div>
      )}
    </div>
  )
}

function CaseDrawer({
  testCase,
  data,
  navigate,
}: {
  testCase: TestCase
  data: AppData
  navigate: Navigate
}) {
  const requirements = data.requirements.filter((item) =>
    testCase.requirementIds.includes(item.id),
  )
  const operations = data.openapi
    .flatMap((item) => item.operations)
    .filter((item) => testCase.operationIds.includes(item.id))
  const run = data.runs.find((item) => item.id === testCase.lastRunId)
  const runCase = run?.cases.find((item) => item.nodeid === testCase.nodeid)

  return (
    <>
      <div
        className="drawer-scrim"
        onClick={() => navigate({ caseNodeid: '' })}
        aria-hidden="true"
      />
      <aside className="detail-drawer" aria-label="用例详情">
        <div className="drawer-head">
          <div className="drawer-heading">
            <span className="eyebrow">PYTEST CASE</span>
            <div className="drawer-title-row">
              <RunStatusBadge status={testCase.lastStatus} />
              <h2>{testCase.name}</h2>
            </div>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="关闭用例详情"
            onClick={() => navigate({ caseNodeid: '' })}
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="drawer-body">
          <div className="drawer-code-block">
            <span className="drawer-label">nodeid</span>
            <code>{testCase.nodeid}</code>
          </div>

          <dl className="meta-list meta-list-wide">
            <div>
              <dt>文件</dt>
              <dd className="mono-strong">{testCase.file}</dd>
            </div>
            <div>
              <dt>最近运行</dt>
              <dd>
                {testCase.lastRunId} · {formatDuration(testCase.lastDurationMs)}
              </dd>
            </div>
            <div>
              <dt>标签</dt>
              <dd>
                <span className="tag-row">
                  {testCase.tags.map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </span>
              </dd>
            </div>
          </dl>

          <section className="drawer-section">
            <div className="rail-title">
              关联需求
              <span className="count-pill">{requirements.length}</span>
            </div>
            {requirements.length ? (
              requirements.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className="rail-requirement rail-requirement-inline"
                  onClick={() =>
                    navigate({
                      module: 'assets',
                      assetTab: 'requirements',
                      requirementId: item.id,
                      caseNodeid: '',
                    })
                  }
                >
                  <span className="mono-id">{item.id}</span>
                  <strong>{item.title}</strong>
                  <span className="rail-requirement-version">{item.version}</span>
                </button>
              ))
            ) : (
              <div className="inline-warning">
                <Icon name="alert" size={14} />
                该用例尚未关联需求，AI 很难判断偏差。
              </div>
            )}
          </section>

          <section className="drawer-section">
            <div className="rail-title">
              关联接口
              <span className="count-pill">{operations.length}</span>
            </div>
            {operations.length ? (
              operations.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className="rail-link"
                  onClick={() =>
                    navigate({
                      module: 'assets',
                      assetTab: 'openapi',
                      docId: item.docId,
                      operationId: item.id,
                      caseNodeid: '',
                    })
                  }
                >
                  <MethodTag method={item.method} />
                  <code>{item.path}</code>
                  <Icon name="arrowRight" size={13} />
                </button>
              ))
            ) : (
              <div className="inline-warning">
                <Icon name="alert" size={14} />
                该用例尚未关联 OpenAPI operation。
              </div>
            )}
          </section>

          {run && runCase && (
            <section className="drawer-section">
              <div className="rail-title">本次运行证据</div>
              <div className="drawer-run-card">
                <div className="drawer-run-head">
                  <span className="mono-id">{run.id}</span>
                  <RunStatusBadge status={runCase.status} />
                </div>
                <div className="drawer-run-meta">
                  {formatDateTime(run.startedAt)} · {run.environment}
                </div>
                <div className="drawer-run-stats">
                  <span>{runCase.exchanges.length} 条 HAR 交换</span>
                  <span>{formatDuration(runCase.durationMs)}</span>
                </div>
              </div>
            </section>
          )}
        </div>

        <div className="drawer-foot">
          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() =>
              navigate({
                module: 'runs',
                runId: testCase.lastRunId,
                evidenceNodeid: testCase.nodeid,
                exchangeIndex: 0,
                caseNodeid: '',
              })
            }
          >
            <Icon name="play" size={14} />
            在运行与审判中查看
          </button>
        </div>
      </aside>
    </>
  )
}

export function CasesView({ data, nav, navigate }: Props) {
  const [keyword, setKeyword] = useState('')
  const [requirementFilter, setRequirementFilter] = useState('all')
  const [operationFilter, setOperationFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<'all' | RunStatus>('all')

  const allOperations = useMemo(
    () => data.openapi.flatMap((item) => item.operations),
    [data.openapi],
  )

  const requirementsCovered = data.requirements.filter((requirement) =>
    data.cases.some((testCase) =>
      testCase.requirementIds.includes(requirement.id),
    ),
  ).length
  const operationsCovered = allOperations.filter((operation) =>
    data.cases.some((testCase) => testCase.operationIds.includes(operation.id)),
  ).length
  const latestRun = data.runs[0]
  const executed = latestRun
    ? latestRun.stats.passed + latestRun.stats.failed + latestRun.stats.error
    : 0
  const passRate = executed ? latestRun.stats.passed / executed : 0
  const requirementCoverage = data.requirements.length
    ? requirementsCovered / data.requirements.length
    : 0
  const operationCoverage = allOperations.length
    ? operationsCovered / allOperations.length
    : 0
  const unlinkedOperationCases = data.cases.filter(
    (item) => item.operationIds.length === 0,
  ).length

  const filtered = useMemo(() => {
    const lower = keyword.trim().toLowerCase()
    return data.cases.filter((testCase) => {
      if (
        lower &&
        !`${testCase.nodeid} ${testCase.name} ${testCase.tags.join(' ')}`
          .toLowerCase()
          .includes(lower)
      ) {
        return false
      }
      if (
        requirementFilter !== 'all' &&
        !testCase.requirementIds.includes(requirementFilter)
      ) {
        return false
      }
      if (
        operationFilter !== 'all' &&
        !testCase.operationIds.includes(operationFilter)
      ) {
        return false
      }
      if (statusFilter !== 'all' && testCase.lastStatus !== statusFilter) {
        return false
      }
      return true
    })
  }, [data.cases, keyword, requirementFilter, operationFilter, statusFilter])

  const selectedCase = nav.caseNodeid
    ? data.cases.find((item) => item.nodeid === nav.caseNodeid)
    : undefined

  return (
    <div className="view">
      <header className="view-head">
        <div>
          <div className="view-kicker">COVERAGE / 02</div>
          <h1 className="view-title">用例覆盖</h1>
          <p className="view-desc">
            pytest 执行后的用例落库，并与需求、OpenAPI operation
            建立追溯关系；未关联的用例会在 AI 审判时缺少契约依据。
          </p>
        </div>
        <div className="head-tags">
          <span className="head-tag">
            <Icon name="terminal" size={13} />
            pytest
          </span>
          <span className="head-tag">
            <Icon name="link" size={13} />
            追溯关系
          </span>
        </div>
      </header>

      <div className="view-body cases-body">
        <div className="stat-grid">
          <StatCard
            label="用例总数"
            value={String(data.cases.length)}
            hint={`${unlinkedOperationCases} 条未关联接口`}
            icon="layers"
          />
          <StatCard
            label="需求覆盖"
            value={`${requirementsCovered} / ${data.requirements.length}`}
            hint={percent(requirementCoverage)}
            progress={requirementCoverage}
            icon="book"
          />
          <StatCard
            label="接口覆盖"
            value={`${operationsCovered} / ${allOperations.length}`}
            hint={`${allOperations.length - operationsCovered} 个 operation 未被覆盖`}
            progress={operationCoverage}
            icon="server"
          />
          <StatCard
            label="最近通过率"
            value={percent(passRate)}
            hint={
              latestRun
                ? `${latestRun.id} · ${latestRun.stats.passed} 通过 / ${executed} 执行`
                : '暂无运行记录'
            }
            progress={passRate}
            icon="shield"
          />
        </div>

        <div className="table-card">
          <div className="table-toolbar">
            <label className="search-field">
              <Icon name="search" size={14} />
              <input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索用例名、nodeid、标签"
                aria-label="搜索用例"
              />
            </label>
            <select
              className="select"
              value={requirementFilter}
              onChange={(event) => setRequirementFilter(event.target.value)}
              aria-label="按需求筛选"
            >
              <option value="all">全部需求</option>
              {data.requirements.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} · {item.title}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={operationFilter}
              onChange={(event) => setOperationFilter(event.target.value)}
              aria-label="按接口筛选"
            >
              <option value="all">全部接口</option>
              {allOperations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.method} {item.path}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as 'all' | RunStatus)
              }
              aria-label="按最近状态筛选"
            >
              {STATUS_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className="toolbar-spacer" />
            <span className="result-count">{filtered.length} 条用例</span>
          </div>

          <div className="table-scroll">
            {filtered.length ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '29%' }}>用例</th>
                    <th style={{ width: '17%' }}>关联需求</th>
                    <th style={{ width: '22%' }}>关联接口</th>
                    <th style={{ width: '14%' }}>最近状态</th>
                    <th style={{ width: '10%' }}>耗时</th>
                    <th style={{ width: '8%' }} />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((testCase) => {
                    const requirement = data.requirements.find((item) =>
                      testCase.requirementIds.includes(item.id),
                    )
                    const operation = allOperations.find((item) =>
                      testCase.operationIds.includes(item.id),
                    )
                    return (
                      <tr
                        key={testCase.nodeid}
                        className="is-clickable"
                        onClick={() =>
                          navigate({ caseNodeid: testCase.nodeid })
                        }
                      >
                        <td>
                          <div className="case-name">{testCase.name}</div>
                          <code className="case-nodeid">{testCase.nodeid}</code>
                        </td>
                        <td>
                          {requirement ? (
                            <span className="link-chip">{requirement.id}</span>
                          ) : (
                            <span className="warn-chip">未关联</span>
                          )}
                        </td>
                        <td>
                          {operation ? (
                            <span className="op-inline">
                              <MethodTag method={operation.method} />
                              <code>{operation.path}</code>
                            </span>
                          ) : (
                            <span className="warn-chip">未关联</span>
                          )}
                        </td>
                        <td>
                          <div className="status-stack">
                            <RunStatusBadge status={testCase.lastStatus} />
                            <span className="cell-sub">
                              {testCase.lastRunId}
                            </span>
                          </div>
                        </td>
                        <td className="num-cell">
                          {formatDuration(testCase.lastDurationMs)}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="icon-btn table-action"
                            aria-label="查看用例详情"
                            onClick={(event) => {
                              event.stopPropagation()
                              navigate({ caseNodeid: testCase.nodeid })
                            }}
                          >
                            <Icon name="chevronRight" size={15} />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            ) : (
              <EmptyState
                icon="search"
                title="没有符合条件的用例"
                description="调整关键词或筛选条件后再试。"
                action={
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setKeyword('')
                      setRequirementFilter('all')
                      setOperationFilter('all')
                      setStatusFilter('all')
                    }}
                  >
                    清除筛选
                  </button>
                }
              />
            )}
          </div>
        </div>
      </div>

      {selectedCase && (
        <CaseDrawer testCase={selectedCase} data={data} navigate={navigate} />
      )}
    </div>
  )
}
