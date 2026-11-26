import { useEffect, useRef, useState } from 'react'
import type {
  AiSummary,
  AppData,
  Defect,
  Finding,
  Navigate,
  NavState,
  Run,
  ToastTone,
  Verdict,
} from '../types'
import { formatDateTime, severityRank } from '../utils/format'
import {
  Confidence,
  EmptyState,
  FindingTypeBadge,
  Icon,
  Segmented,
  SeverityBadge,
  VerdictStamp,
} from './ui'

interface Props {
  run: Run
  nodeid: string
  data: AppData
  nav: NavState
  navigate: Navigate
  summary?: AiSummary
  onJudge: (
    id: string,
    verdict: Verdict,
    note: string,
  ) => Promise<{ finding: Finding; defect?: Defect }>
  onToast: (text: string, tone?: ToastTone) => void
  open?: boolean
  onClose?: () => void
}

type Filter = 'pending' | 'judged' | 'all'

const NOTE_CHIPS: Record<Verdict, string[]> = {
  confirm: ['证据充分，确认为真实缺陷', '影响发布，需要立即修复', '建议补充边界用例'],
  reject: ['证据不足，暂不成立', '需求已变更，不构成缺陷', '已有处理记录，重复'],
  'false-positive': ['环境问题，非产品缺陷', 'AI 误读响应状态', '预期行为，无需修复'],
}

function findingVerdict(status: Finding['status']): Verdict {
  if (status === 'confirmed') return 'confirm'
  if (status === 'rejected') return 'reject'
  return 'false-positive'
}

export function FindingsPanel({
  run,
  nodeid,
  data,
  nav,
  navigate,
  summary,
  onJudge,
  onToast,
  open,
  onClose,
}: Props) {
  const [filter, setFilter] = useState<Filter>('pending')
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [otherOpen, setOtherOpen] = useState(false)
  const activeCardRef = useRef<HTMLElement | null>(null)

  const caseFindings = data.findings.filter(
    (item) => item.runId === run.id && item.nodeid === nodeid,
  )
  const otherFindings = data.findings
    .filter((item) => item.runId === run.id && item.nodeid !== nodeid)
    .sort(
      (left, right) =>
        (left.status === 'pending' ? 0 : 1) -
          (right.status === 'pending' ? 0 : 1) ||
        severityRank[left.suggestedSeverity] -
          severityRank[right.suggestedSeverity],
    )
  const pendingCount = caseFindings.filter(
    (item) => item.status === 'pending',
  ).length
  const judgedCount = caseFindings.length - pendingCount
  const otherPending = otherFindings.filter(
    (item) => item.status === 'pending',
  ).length
  const filtered = caseFindings
    .filter((item) => {
      if (filter === 'pending') return item.status === 'pending'
      if (filter === 'judged') return item.status !== 'pending'
      return true
    })
    .sort(
      (left, right) =>
        severityRank[left.suggestedSeverity] -
          severityRank[right.suggestedSeverity] ||
        right.createdAt.localeCompare(left.createdAt),
    )

  useEffect(() => {
    setVerdict(null)
    setNote('')
    setFilter('pending')
    setOtherOpen(false)
  }, [run.id, nodeid])

  useEffect(() => {
    setVerdict(null)
    setNote('')
  }, [nav.findingId])

  useEffect(() => {
    if (!nav.findingId) return
    const target = data.findings.find((item) => item.id === nav.findingId)
    if (target) {
      setFilter(target.status === 'pending' ? 'pending' : 'judged')
    }
  }, [data.findings, nav.findingId])

  useEffect(() => {
    activeCardRef.current?.scrollIntoView({ block: 'nearest' })
  }, [filter, nodeid, nav.findingId, run.id])

  const submitJudge = async (finding: Finding) => {
    if (!verdict || submitting) return
    setSubmitting(true)
    try {
      await onJudge(finding.id, verdict, note.trim())
      setVerdict(null)
      setNote('')
      const next = data.findings
        .filter(
          (item) => item.status === 'pending' && item.id !== finding.id,
        )
        .sort(
          (left, right) =>
            severityRank[left.suggestedSeverity] -
              severityRank[right.suggestedSeverity] ||
            right.createdAt.localeCompare(left.createdAt),
        )[0]
      navigate({
        findingId: next?.id ?? '',
        ...(next
          ? {
              runId: next.runId,
              evidenceNodeid: next.nodeid,
              exchangeIndex: next.exchangeIndex ?? 0,
            }
          : {}),
      })
    } catch {
      onToast('提交审判失败，请重试', 'danger')
    } finally {
      setSubmitting(false)
    }
  }

  const summaryParagraphs = (summary?.text ?? '')
    .split('\n\n')
    .map((item) => item.trim())
    .filter(Boolean)

  return (
    <aside className={`pane pane-right ${open ? 'is-open' : ''}`}>
      <div className="trial-head">
        <div>
          <span className="eyebrow">AI ANALYSIS / 裁决</span>
          <h2>AI 审判</h2>
          <p>审阅左侧选中用例的 AI 发现；批次级分析见上方。</p>
        </div>
        <div className="trial-head-actions">
          {onClose && (
            <button
              type="button"
              className="icon-btn trial-close"
              aria-label="关闭审判面板"
              onClick={onClose}
            >
              <Icon name="x" size={16} />
            </button>
          )}
        </div>
      </div>

      <div className="trial-body">
        <div className="ai-summary-card">
          <div className="ai-card-head">
            <span className="ai-card-label">
              <Icon name="file" size={14} />
              运行级分析
            </span>
            {summary && <span className="source-tag">已落库</span>}
          </div>

          {summary ? (
            <>
              <div className="ai-summary-text">
                {summaryParagraphs.map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
              </div>
              <div className="ai-card-foot">
                <span>{summary.analyzer}</span>
                <span>{summary.model}</span>
                <span className="ai-card-time">
                  落库 {formatDateTime(summary.generatedAt)}
                </span>
              </div>
            </>
          ) : (
            <p className="ai-placeholder">
              本次运行尚未收到外部分析结果。pytest 结束后由分析流水线写入，平台只读取结果，不在页面内触发分析。
            </p>
          )}
        </div>

        <div className="findings-head">
          <h3>
            本用例 AI 发现
            <span className="count-pill">{caseFindings.length}</span>
          </h3>
          <Segmented
            size="sm"
            value={filter}
            onChange={(value) => setFilter(value)}
            options={[
              { value: 'pending', label: '待审判', count: pendingCount },
              { value: 'judged', label: '已处理', count: judgedCount },
              { value: 'all', label: '全部', count: caseFindings.length },
            ]}
          />
        </div>

        <div className="findings-list">
          {filtered.length ? (
            filtered.map((finding) => {
              const active = nav.findingId === finding.id
              const isPending = finding.status === 'pending'
              return (
                <article
                  key={finding.id}
                  ref={active ? activeCardRef : undefined}
                  className={`finding-card ${active ? 'is-active' : ''} ${
                    isPending ? '' : 'is-judged'
                  }`}
                  onClick={() =>
                    navigate({
                      findingId: finding.id,
                      evidenceNodeid: finding.nodeid,
                      exchangeIndex: finding.exchangeIndex ?? 0,
                    })
                  }
                >
                  <div className="finding-top">
                    <FindingTypeBadge type={finding.type} />
                    <SeverityBadge severity={finding.suggestedSeverity} />
                    <div className="toolbar-spacer" />
                    <Confidence value={finding.confidence} />
                  </div>
                  <h4 className="finding-title">{finding.title}</h4>
                  <p className="finding-summary">{finding.summary}</p>
                  <div className="finding-meta">
                    <span className="finding-case">
                      <Icon name="file" size={12} />
                      {finding.nodeid.split('::')[1] ?? finding.nodeid}
                    </span>
                    {typeof finding.exchangeIndex === 'number' && (
                      <button
                        type="button"
                        className="inline-link"
                        onClick={(event) => {
                          event.stopPropagation()
                          navigate({
                            findingId: finding.id,
                            evidenceNodeid: finding.nodeid,
                            exchangeIndex: finding.exchangeIndex ?? 0,
                          })
                        }}
                      >
                        第 {finding.exchangeIndex + 1} 次交换
                      </button>
                    )}
                  </div>

                  {active && (
                    <div className="finding-detail">
                      <div className="finding-field">
                        <span className="field-label">根因判断</span>
                        <p>{finding.rootCause}</p>
                      </div>
                      <div className="finding-field">
                        <span className="field-label">影响范围</span>
                        <p>{finding.impact}</p>
                      </div>

                      {isPending ? (
                        <div className="judge-form">
                          <div className="judge-form-head">
                            <span className="field-label">你的裁决</span>
                            <span className="judge-hint">确认后才会生成缺陷</span>
                          </div>
                          <div className="verdict-buttons">
                            <button
                              type="button"
                              className={`verdict-btn verdict-btn-confirm ${
                                verdict === 'confirm' ? 'is-active' : ''
                              }`}
                              onClick={(event) => {
                                event.stopPropagation()
                                setVerdict('confirm')
                              }}
                            >
                              <Icon name="check" size={14} />
                              确认缺陷
                            </button>
                            <button
                              type="button"
                              className={`verdict-btn verdict-btn-reject ${
                                verdict === 'reject' ? 'is-active' : ''
                              }`}
                              onClick={(event) => {
                                event.stopPropagation()
                                setVerdict('reject')
                              }}
                            >
                              <Icon name="x" size={14} />
                              驳回
                            </button>
                            <button
                              type="button"
                              className={`verdict-btn verdict-btn-false ${
                                verdict === 'false-positive' ? 'is-active' : ''
                              }`}
                              onClick={(event) => {
                                event.stopPropagation()
                                setVerdict('false-positive')
                              }}
                            >
                              <Icon name="alert" size={14} />
                              误报
                            </button>
                          </div>
                          <textarea
                            className="textarea"
                            value={note}
                            rows={3}
                            placeholder="补充判断依据（可选），例如复现条件、环境差异、历史缺陷编号"
                            onClick={(event) => event.stopPropagation()}
                            onChange={(event) => setNote(event.target.value)}
                          />
                          {verdict && (
                            <div className="note-chips">
                              {NOTE_CHIPS[verdict].map((chip) => (
                                <button
                                  type="button"
                                  className="note-chip"
                                  key={chip}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setNote(chip)
                                  }}
                                >
                                  {chip}
                                </button>
                              ))}
                            </div>
                          )}
                          <button
                            type="button"
                            className="btn btn-primary btn-block"
                            disabled={!verdict || submitting}
                            onClick={(event) => {
                              event.stopPropagation()
                              submitJudge(finding)
                            }}
                          >
                            {submitting ? '提交中…' : '提交审判'}
                          </button>
                        </div>
                      ) : (
                        <div className="judged-block">
                          <div className="judged-head">
                            <VerdictStamp verdict={findingVerdict(finding.status)} />
                            <span className="judged-time">
                              {finding.judgedAt
                                ? formatDateTime(finding.judgedAt)
                                : '—'}
                            </span>
                            {finding.defectId && (
                              <button
                                type="button"
                                className="inline-link"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  navigate({
                                    module: 'defects',
                                    defectId: finding.defectId ?? '',
                                  })
                                }}
                              >
                                查看缺陷 {finding.defectId}
                              </button>
                            )}
                          </div>
                          <p className="judged-note">
                            {finding.note || '未填写审判理由。'}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </article>
              )
            })
          ) : (
            <EmptyState
              icon="shield"
              title={
                caseFindings.length === 0
                  ? '本用例没有 AI 发现'
                  : filter === 'pending'
                    ? '本用例的发现已全部审判'
                    : '本用例暂无已处理发现'
              }
              description={
                caseFindings.length === 0
                  ? '展开下方「本批次其他发现」查看其他用例，或切换到有发现的用例。'
                  : filter === 'pending'
                    ? '切换「已处理」回看裁决记录。'
                    : '外部分析流水线尚未写入该用例的发现。'
              }
              action={
                filter === 'pending' && caseFindings.length > 0 ? (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setFilter('judged')}
                  >
                    查看已处理
                  </button>
                ) : undefined
              }
            />
          )}
        </div>

        {otherFindings.length > 0 && (
          <div className="other-findings-block">
            <button
              type="button"
              className="other-findings-toggle"
              onClick={() => setOtherOpen((prev) => !prev)}
            >
              <Icon name={otherOpen ? 'chevronDown' : 'chevronRight'} size={13} />
              本批次其他发现
              <span className="count-pill">{otherFindings.length}</span>
              {otherPending > 0 && (
                <span className="warn-chip">{otherPending} 待审判</span>
              )}
            </button>
            {otherOpen && (
              <div className="other-findings">
                {otherFindings.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="other-finding-row"
                    onClick={() =>
                      navigate({
                        findingId: item.id,
                        evidenceNodeid: item.nodeid,
                        exchangeIndex: item.exchangeIndex ?? 0,
                      })
                    }
                  >
                    <SeverityBadge severity={item.suggestedSeverity} />
                    <span className="other-title">{item.title}</span>
                    <span className="other-case">
                      {item.nodeid.split('::')[1] ?? item.nodeid}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
