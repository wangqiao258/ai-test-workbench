import { useMemo, useState } from 'react'
import type {
  AppData,
  Defect,
  DefectStatus,
  Navigate,
  NavState,
  Severity,
  ToastTone,
} from '../types'
import {
  formatDateTime,
  formatFullTime,
  severityLabel,
  statusLabel,
} from '../utils/format'
import {
  Confidence,
  EmptyState,
  Icon,
  MethodTag,
  SeverityBadge,
  VerdictStamp,
} from './ui'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  onStatusChange: (id: string, status: DefectStatus) => Promise<void>
  onToast: (text: string, tone?: ToastTone) => void
}

const STATUS_ORDER: DefectStatus[] = [
  'new',
  'confirmed',
  'fixing',
  'fixed',
  'closed',
]

export function DefectsView({
  data,
  nav,
  navigate,
  onStatusChange,
  onToast,
}: Props) {
  const [keyword, setKeyword] = useState('')
  const [severityFilter, setSeverityFilter] = useState<'all' | Severity>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | DefectStatus>('all')

  const selected =
    data.defects.find((item) => item.id === nav.defectId) ?? data.defects[0]

  const filtered = useMemo(() => {
    const lower = keyword.trim().toLowerCase()
    return data.defects.filter((defect) => {
      if (
        lower &&
        !`${defect.id} ${defect.title} ${defect.nodeid}`
          .toLowerCase()
          .includes(lower)
      ) {
        return false
      }
      if (severityFilter !== 'all' && defect.severity !== severityFilter) {
        return false
      }
      if (statusFilter !== 'all' && defect.status !== statusFilter) {
        return false
      }
      return true
    })
  }, [data.defects, keyword, severityFilter, statusFilter])

  const finding = selected?.findingId
    ? data.findings.find((item) => item.id === selected.findingId)
    : undefined
  const requirement = selected?.requirementId
    ? data.requirements.find((item) => item.id === selected.requirementId)
    : undefined
  const operation = selected?.operationId
    ? data.openapi
        .flatMap((item) => item.operations)
        .find((item) => item.id === selected.operationId)
    : undefined
  const runExists = selected
    ? data.runs.some((item) => item.id === selected.runId)
    : false

  const openInRun = (defect: Defect) => {
    if (!runExists) {
      onToast('该缺陷来自历史批次，当前项目未保留运行证据', 'info')
      return
    }
    navigate({
      module: 'runs',
      runId: defect.runId,
      evidenceNodeid: defect.nodeid,
      exchangeIndex: defect.exchangeIndex ?? 0,
      findingId: defect.findingId ?? '',
    })
  }

  return (
    <div className="view">
      <header className="view-head">
        <div>
          <div className="view-kicker">VERDICT ARCHIVE / 04</div>
          <h1 className="view-title">缺陷库</h1>
          <p className="view-desc">
            只收录经过人工确认的缺陷。每条缺陷保留运行证据与审判记录，AI
            判断仅作为历史依据，不再直接展示分析结论。
          </p>
        </div>
        <div className="head-tags">
          <span className="head-tag">
            <Icon name="shield" size={13} />
            人工确认 {data.defects.length}
          </span>
          <span className="head-tag">
            <Icon name="spark" size={13} />
            AI 建议仅留痕
          </span>
        </div>
      </header>

      <div className="view-body">
        <div className="defects-body">
        <div className="defect-list-pane">
          <div className="list-pane-head">
            <div>
              <span className="eyebrow">DEFECTS</span>
              <h2>
                已确认缺陷
                <span className="count-pill">{data.defects.length}</span>
              </h2>
            </div>
          </div>

          <div className="list-filters">
            <label className="search-field">
              <Icon name="search" size={14} />
              <input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索 ID、标题、nodeid"
                aria-label="搜索缺陷"
              />
            </label>
            <div className="filter-row">
              <select
                className="select select-sm"
                value={severityFilter}
                onChange={(event) =>
                  setSeverityFilter(event.target.value as 'all' | Severity)
                }
                aria-label="按严重级别筛选"
              >
                <option value="all">全部级别</option>
                {(['blocker', 'critical', 'major', 'minor'] as Severity[]).map(
                  (item) => (
                    <option key={item} value={item}>
                      {severityLabel[item]}
                    </option>
                  ),
                )}
              </select>
              <select
                className="select select-sm"
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(event.target.value as 'all' | DefectStatus)
                }
                aria-label="按状态筛选"
              >
                <option value="all">全部状态</option>
                {STATUS_ORDER.map((item) => (
                  <option key={item} value={item}>
                    {statusLabel[item]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="defect-list-scroll">
            {filtered.length ? (
              filtered.map((defect) => (
                <button
                  key={defect.id}
                  type="button"
                  className={`defect-row ${
                    selected?.id === defect.id ? 'is-active' : ''
                  }`}
                  onClick={() => navigate({ defectId: defect.id })}
                >
                  <span className={`severity-bar severity-bar-${defect.severity}`} />
                  <div className="defect-row-main">
                    <div className="defect-row-top">
                      <span className="mono-id">{defect.id}</span>
                      <span className={`defect-state state-${defect.status}`}>
                        {statusLabel[defect.status]}
                      </span>
                    </div>
                    <div className="defect-row-title">{defect.title}</div>
                    <div className="defect-row-meta">
                      <span>{defect.nodeid.split('::')[1] ?? defect.nodeid}</span>
                      <span>{formatDateTime(defect.createdAt)}</span>
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <EmptyState
                icon="search"
                title="没有符合条件的缺陷"
                description="调整关键词或筛选条件后再试。"
              />
            )}
          </div>
        </div>

        <div className="defect-detail-pane">
          {selected ? (
            <div className="defect-detail-scroll">
              <div className="defect-detail-head">
                <div className="defect-head-top">
                  <span className="mono-id defect-id">{selected.id}</span>
                  <SeverityBadge severity={selected.severity} />
                  <div className="toolbar-spacer" />
                  <label className="status-select-wrap">
                    <span>状态</span>
                    <select
                      className="select select-sm"
                      value={selected.status}
                      onChange={(event) =>
                        onStatusChange(
                          selected.id,
                          event.target.value as DefectStatus,
                        )
                      }
                      aria-label="修改缺陷状态"
                    >
                      {STATUS_ORDER.map((item) => (
                        <option key={item} value={item}>
                          {statusLabel[item]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <h1 className="defect-title">{selected.title}</h1>
                <div className="defect-submeta">
                  <span>
                    <Icon name="spark" size={13} />
                    来源：{selected.source}
                  </span>
                  <span>
                    <Icon name="clock" size={13} />
                    创建于 {formatFullTime(selected.createdAt)}
                  </span>
                  <span>
                    <Icon name="refresh" size={13} />
                    更新于 {formatDateTime(selected.updatedAt)}
                  </span>
                </div>
              </div>

              <section className="detail-section">
                <h2 className="detail-section-title">关联资产</h2>
                <div className="asset-link-grid">
                  <div className="asset-link-card">
                    <span className="asset-link-label">需求</span>
                    {requirement ? (
                      <button
                        type="button"
                        className="asset-link-value"
                        onClick={() =>
                          navigate({
                            module: 'assets',
                            assetTab: 'requirements',
                            requirementId: requirement.id,
                          })
                        }
                      >
                        <span className="mono-id">{requirement.id}</span>
                        <strong>{requirement.title}</strong>
                        <Icon name="arrowRight" size={14} />
                      </button>
                    ) : (
                      <span className="asset-link-empty">未关联需求</span>
                    )}
                  </div>
                  <div className="asset-link-card">
                    <span className="asset-link-label">接口</span>
                    {operation ? (
                      <button
                        type="button"
                        className="asset-link-value"
                        onClick={() =>
                          navigate({
                            module: 'assets',
                            assetTab: 'openapi',
                            docId: operation.docId,
                            operationId: operation.id,
                          })
                        }
                      >
                        <MethodTag method={operation.method} />
                        <code>{operation.path}</code>
                        <Icon name="arrowRight" size={14} />
                      </button>
                    ) : (
                      <span className="asset-link-empty">未关联接口</span>
                    )}
                  </div>
                  <div className="asset-link-card">
                    <span className="asset-link-label">用例</span>
                    <button
                      type="button"
                      className="asset-link-value"
                      onClick={() =>
                        navigate({ module: 'cases', caseNodeid: selected.nodeid })
                      }
                    >
                      <Icon name="file" size={13} />
                      <code>{selected.nodeid.split('::')[1]}</code>
                      <Icon name="arrowRight" size={14} />
                    </button>
                  </div>
                </div>
              </section>

              <section className="detail-section">
                <h2 className="detail-section-title">运行证据</h2>
                <div className="evidence-link-card">
                  <div className="evidence-link-main">
                    <span className="mono-id">{selected.runId}</span>
                    <code>{selected.nodeid}</code>
                    <p>{selected.evidenceSummary}</p>
                  </div>
                  <button
                    type="button"
                    className="btn btn-soft"
                    onClick={() => openInRun(selected)}
                  >
                    <Icon name="terminal" size={14} />
                    {runExists ? '查看请求 / 响应' : '历史批次未保留运行记录'}
                  </button>
                </div>
              </section>

              <section className="detail-section">
                <h2 className="detail-section-title">审判记录</h2>
                <div className="audit-trail">
                  <div className="audit-item">
                    <span className="audit-node audit-node-final">
                      <Icon name="shield" size={14} />
                    </span>
                    <div className="audit-body">
                      <div className="audit-head">
                        <VerdictStamp verdict={selected.decision.verdict} />
                        <span className="audit-time">
                          {formatFullTime(selected.decision.at)}
                        </span>
                      </div>
                      <p className="audit-note">
                        {selected.decision.note || '未填写审判理由。'}
                      </p>
                      <div className="audit-meta">
                        {selected.findingId && (
                          <span>
                            来源 AI 发现：
                            <button
                              type="button"
                              className="inline-link"
                              onClick={() => {
                                if (!finding) {
                                  onToast('该 AI 发现未关联当前运行数据', 'info')
                                  return
                                }
                                navigate({
                                  module: 'runs',
                                  runId: finding.runId,
                                  evidenceNodeid: finding.nodeid,
                                  exchangeIndex: finding.exchangeIndex ?? 0,
                                  findingId: finding.id,
                                })
                              }}
                            >
                              {selected.findingId}
                            </button>
                          </span>
                        )}
                        {finding && (
                          <span>
                            AI 置信度 <Confidence value={finding.confidence} />
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="audit-item">
                    <span className="audit-node">
                      <Icon name="bug" size={14} />
                    </span>
                    <div className="audit-body">
                      <div className="audit-head">
                        <strong>缺陷入库</strong>
                        <span className="audit-time">
                          {formatFullTime(selected.createdAt)}
                        </span>
                      </div>
                      <p className="audit-note">
                        人工确认后由工作台生成，保留原始运行证据与 AI
                        发现引用，不自动改变状态。
                      </p>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          ) : (
            <EmptyState
              icon="bug"
              title="还没有已确认缺陷"
              description="在「运行与审判」中确认 AI 发现后，缺陷会出现在这里。"
              action={
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => navigate({ module: 'runs' })}
                >
                  前往审判台
                </button>
              }
            />
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
