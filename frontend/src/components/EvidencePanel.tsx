import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  AppData,
  Exchange,
  Finding,
  Navigate,
  NavState,
  RunCase,
  TestCase,
  ToastTone,
} from '../types'
import {
  formatDuration,
  logLevel,
  severityLabel,
  severityRank,
} from '../utils/format'
import {
  Confidence,
  CopyButton,
  EmptyState,
  Icon,
  MethodTag,
  RunStatusBadge,
  SeverityBadge,
} from './ui'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  runId: string
  runCase: RunCase
  testCase?: TestCase
  pendingCount: number
  loading?: boolean
  onOpenTrial: () => void
  onToast: (text: string, tone?: ToastTone) => void
}

function shortUrl(url: string): string {
  try {
    const parsed = new URL(url)
    return `${parsed.pathname}${parsed.search}`
  } catch {
    return url
  }
}

function rawRequest(exchange: Exchange): string {
  let target = exchange.url
  let host = ''
  try {
    const parsed = new URL(exchange.url)
    target = `${parsed.pathname}${parsed.search}`
    host = parsed.host
  } catch {
    // 非法 URL 时保留原始地址
  }
  return [
    `${exchange.method} ${target} HTTP/1.1`,
    ...(host ? [`Host: ${host}`] : []),
    ...exchange.request.headers.map(
      (header) => `${header.name}: ${header.value}`,
    ),
    '',
    exchange.request.body,
  ].join('\n')
}

function rawResponse(exchange: Exchange): string {
  return [
    `HTTP/1.1 ${exchange.status}`,
    ...exchange.response.headers.map(
      (header) => `${header.name}: ${header.value}`,
    ),
    '',
    exchange.response.body,
  ].join('\n')
}

function statusClass(status: number): string {
  if (status >= 500) return 'is-error'
  if (status >= 400) return 'is-warn'
  if (status >= 300) return 'is-info'
  return 'is-ok'
}

export function EvidencePanel({
  data,
  nav,
  navigate,
  runId,
  runCase,
  testCase,
  pendingCount,
  loading = false,
  onOpenTrial,
  onToast,
}: Props) {
  const exchange =
    runCase.exchanges.find((item) => item.index === nav.exchangeIndex) ??
    runCase.exchanges[0]
  const exchangeTotal = runCase.exchanges.length || runCase.exchangeCount

  const [focusFlash, setFocusFlash] = useState(false)
  const detailRef = useRef<HTMLElement | null>(null)
  const manualExchangeRef = useRef(false)
  const lastFocusRef = useRef('')

  const activeFinding = nav.findingId
    ? data.findings.find(
        (item) =>
          item.id === nav.findingId &&
          item.runId === runId &&
          item.nodeid === runCase.nodeid,
      )
    : undefined
  const findingExchangeIndex = activeFinding?.exchangeIndex

  const findingsByExchange = useMemo(() => {
    const map = new Map<number, Finding[]>()
    for (const item of data.findings) {
      if (item.runId !== runId || item.nodeid !== runCase.nodeid) continue
      if (typeof item.exchangeIndex !== 'number') continue
      const bucket = map.get(item.exchangeIndex)
      if (bucket) bucket.push(item)
      else map.set(item.exchangeIndex, [item])
    }
    for (const bucket of map.values()) {
      bucket.sort(
        (left, right) =>
          severityRank[left.suggestedSeverity] -
          severityRank[right.suggestedSeverity],
      )
    }
    return map
  }, [data.findings, runCase.nodeid, runId])

  useEffect(() => {
    const manual = manualExchangeRef.current
    manualExchangeRef.current = false
    if (manual || !nav.findingId || loading || !exchange) {
      lastFocusRef.current = ''
      return
    }
    const key = `${nav.findingId}::${nav.exchangeIndex}::${runCase.nodeid}`
    if (lastFocusRef.current === key) return
    lastFocusRef.current = key
    detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFocusFlash(true)
    const timer = window.setTimeout(() => setFocusFlash(false), 1500)
    return () => window.clearTimeout(timer)
  }, [exchange, loading, nav.exchangeIndex, nav.findingId, runCase.nodeid])

  const requestRaw = exchange ? rawRequest(exchange) : ''
  const responseRaw = exchange ? rawResponse(exchange) : ''

  const requirement = data.requirements.find((item) =>
    testCase?.requirementIds.includes(item.id),
  )
  const operation = data.openapi
    .flatMap((item) => item.operations)
    .find((item) => testCase?.operationIds.includes(item.id))

  return (
    <section className="pane pane-center">
      <div className="evidence-head">
        <div className="evidence-crumb">
          <span className="crumb-run">{runId}</span>
          <Icon name="chevronRight" size={11} />
          <span className="crumb-case">{runCase.nodeid}</span>
          {nav.findingId && (
            <>
              <Icon name="chevronRight" size={11} />
              <span className="crumb-finding" title={activeFinding?.title}>
                {activeFinding
                  ? `${severityLabel[activeFinding.suggestedSeverity]} · ${
                      activeFinding.title
                    }`
                  : nav.findingId}
              </span>
            </>
          )}
        </div>
        <div className="evidence-title-row">
          <RunStatusBadge status={runCase.status} />
          <h2 className="evidence-title">
            {testCase?.name ?? runCase.nodeid.split('::')[1]}
          </h2>
          <span className="time-chip">{formatDuration(runCase.durationMs)}</span>
          <div className="toolbar-spacer" />
          <button
            type="button"
            className="btn btn-soft trial-trigger"
            onClick={onOpenTrial}
          >
            <Icon name="spark" size={14} />
            AI 审判
            {pendingCount > 0 && <span className="btn-badge">{pendingCount}</span>}
          </button>
        </div>
        <div className="evidence-meta">
          <code className="evidence-nodeid">{runCase.nodeid}</code>
          <span className="meta-divider" />
          {requirement ? (
            <button
              type="button"
              className="meta-link"
              onClick={() =>
                navigate({
                  module: 'assets',
                  assetTab: 'requirements',
                  requirementId: requirement.id,
                })
              }
            >
              <Icon name="book" size={13} />
              {requirement.id}
            </button>
          ) : (
            <span className="meta-muted">未关联需求</span>
          )}
          {operation ? (
            <button
              type="button"
              className="meta-link"
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
              {operation.path}
            </button>
          ) : (
            <span className="meta-muted">未关联接口</span>
          )}
        </div>
      </div>

      <div className="evidence-body">
        {runCase.error && (
          <div className="error-box">
            <div className="error-box-head">
              <span>
                <Icon name="alert" size={14} />
                运行失败
              </span>
              <CopyButton
                text={`${runCase.error}\n${runCase.logs.join('\n')}`}
                onCopied={() => onToast('失败信息已复制', 'success')}
                label="复制"
              />
            </div>
            <pre className="error-text">{runCase.error}</pre>
          </div>
        )}

        <section className="panel">
          <div className="panel-head">
            <h3>
              抓包交换
              <span className="count-pill">{exchangeTotal}</span>
            </h3>
          </div>
          {loading ? (
            <div className="case-list-empty">正在加载抓包证据…</div>
          ) : runCase.exchanges.length ? (
            <div className="exchange-list">
              {runCase.exchanges.map((item) => {
                const active = item.index === exchange?.index
                const aiFindings = findingsByExchange.get(item.index)
                const aiPending = aiFindings?.some(
                  (finding) => finding.status === 'pending',
                )
                return (
                  <button
                    key={item.index}
                    type="button"
                    className={`exchange-row ${active ? 'is-active' : ''}`}
                    onClick={() => {
                      if (active) return
                      manualExchangeRef.current = true
                      navigate({ exchangeIndex: item.index })
                    }}
                  >
                    <span className="exchange-index">#{item.index + 1}</span>
                    <MethodTag method={item.method} />
                    <span className="exchange-path">
                      {shortUrl(item.url)}
                    </span>
                    {aiFindings && (
                      <span
                        className={`exchange-ai ${
                          aiPending ? 'is-pending' : ''
                        }`}
                        title={`${aiFindings.length} 条 AI 发现：${
                          aiFindings[0]?.title ?? ''
                        }`}
                      >
                        <Icon name="spark" size={11} />
                        {aiFindings.length}
                      </span>
                    )}
                    <span className={`http-status ${statusClass(item.status)}`}>
                      {item.status}
                    </span>
                    <span className="exchange-time">
                      {formatDuration(item.elapsedMs)}
                    </span>
                    {item.error && (
                      <span className="exchange-error">
                        <Icon name="alert" size={12} />
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          ) : (
            <EmptyState
              icon="server"
              title="本次用例没有抓包记录"
              description="确认运行时已开启 --capture-traffic，或该用例没有发起 HTTP 请求。"
            />
          )}
        </section>

        <section
          className={`panel ${focusFlash ? 'is-focus' : ''}`}
          ref={detailRef}
        >
          <div className="panel-head">
            <h3>
              交换详情
              <span className="count-pill">{exchangeTotal}</span>
            </h3>
            {exchange && (
              <span className="panel-hint">第 {exchange.index + 1} 次交换</span>
            )}
          </div>

          {activeFinding && (
            <div className="evidence-finding-bar">
              <span className="evidence-finding-label">
                <Icon name="spark" size={12} />
                当前发现
              </span>
              <span
                className="evidence-finding-title"
                title={activeFinding.title}
              >
                {activeFinding.title}
              </span>
              <span className="evidence-finding-meta">
                <SeverityBadge severity={activeFinding.suggestedSeverity} />
                <Confidence value={activeFinding.confidence} />
                {typeof findingExchangeIndex === 'number' &&
                  findingExchangeIndex !== exchange?.index && (
                    <button
                      type="button"
                      className="inline-link"
                      onClick={() =>
                        navigate({ exchangeIndex: findingExchangeIndex })
                      }
                    >
                      定位第 {findingExchangeIndex + 1} 次交换
                    </button>
                  )}
              </span>
            </div>
          )}

          {loading ? (
            <div className="case-list-empty">正在加载抓包证据…</div>
          ) : exchange ? (
            <div className="exchange-detail">
              <div className="detail-part">
                <div className="detail-part-head">
                  <span className="detail-part-title">请求</span>
                  <CopyButton
                    text={requestRaw}
                    onCopied={() => onToast('原始请求已复制', 'success')}
                    label="复制原始请求"
                  />
                </div>
                <pre className="raw-block">{requestRaw}</pre>
              </div>

              <div className="detail-part">
                <div className="detail-part-head">
                  <span className="detail-part-title">响应</span>
                  <CopyButton
                    text={responseRaw}
                    onCopied={() => onToast('原始响应已复制', 'success')}
                    label="复制原始响应"
                  />
                </div>
                <pre className="raw-block">{responseRaw}</pre>
              </div>

              <details className="logs-block">
                <summary>
                  <span>运行日志</span>
                  <span className="count-pill">{runCase.logs.length}</span>
                  <span className="logs-hint" />
                </summary>
                {runCase.logs.length ? (
                  <div className="log-view">
                    {runCase.logs.map((line, index) => (
                      <div
                        className={`log-line log-${logLevel(line)}`}
                        key={index}
                      >
                        <span className="log-no">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <code>{line}</code>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted-line logs-empty">没有日志输出</p>
                )}
              </details>
            </div>
          ) : (
            <EmptyState icon="file" title="没有可查看的交换" />
          )}
        </section>
      </div>
    </section>
  )
}
