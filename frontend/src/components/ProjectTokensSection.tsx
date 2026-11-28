import { useEffect, useState } from 'react'
import type { ProjectToken } from '../types'
import { api, type TokenMeta } from '../services/api'
import { copyText, formatDateTime } from '../utils/format'
import { Icon } from './ui'

const STATUS_LABELS: Record<ProjectToken['status'], string> = {
  active: '有效',
  revoked: '已吊销',
  expired: '已过期',
}

const buildAiPrompt = (secret: string, scopes: string[]) =>
  `你正在接入 AI Test Workbench。\n先读取能力：curl -s -H "X-Project-Token: ${secret}" ${window.location.origin}/ingest/v1/whoami\n本令牌权限：${scopes.join('、') || '未知'}。` +
  `${scopes.length > 0 && scopes.every((s) => s.startsWith('assets:')) ? '这是资产令牌：只做需求/OpenAPI/接口检索，不要读取运行、发现、缺陷，不要上传运行或分析，不要读取测试凭据。' : '只执行 scopes 覆盖的动作，无权限的直接跳过。'}` +
  `以 whoami 返回的 scopes 为准。\n然后按返回的 project、rules、actions 执行；接口与需求走 /ingest/v1/*。\n文档：${window.location.origin}/ingest/docs\n注意：这是长期令牌，请勿粘贴到不可信的 AI 对话或公开日志。`

interface Props {
  projectId: string
}

export function ProjectTokensSection({ projectId }: Props) {
  const [tokens, setTokens] = useState<ProjectToken[]>([])
  const [meta, setMeta] = useState<TokenMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [presetId, setPresetId] = useState('')
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<{
    token: ProjectToken
    secret: string
  } | null>(null)
  const [copied, setCopied] = useState<'token' | ''>('')
  const [copiedRow, setCopiedRow] = useState('')
  const [revokeId, setRevokeId] = useState<string | null>(null)
  const [revoking, setRevoking] = useState(false)
  const [purgeId, setPurgeId] = useState<string | null>(null)
  const [purging, setPurging] = useState(false)
  const [purgeAllArmed, setPurgeAllArmed] = useState(false)
  const [purgingAll, setPurgingAll] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    api
      .listProjectTokens(projectId)
      .then(async (rows) => {
        if (!alive) return
        setTokens(rows)
        const loaded = await api.fetchTokenMeta()
        if (!alive) return
        setMeta(loaded)
        setPresetId(loaded.presets[0]?.id ?? '')
      })
      .catch((err) => {
        if (alive) {
          setError(err instanceof Error ? err.message : '读取接入令牌失败')
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [projectId])

  const preset =
    meta?.presets.find((item) => item.id === presetId) ?? meta?.presets[0]
  const scopeLabels = Object.fromEntries(
    (meta?.scopes ?? []).map((scope) => [scope.id, scope.label]),
  )
  const activeCount = tokens.filter((token) => token.status === 'active').length
  const inactiveCount = tokens.length - activeCount

  const create = async () => {
    if (creating) return
    const trimmed = name.trim()
    if (!trimmed) {
      setError('请填写令牌名称')
      return
    }
    if (!preset) {
      setError('权限预设未加载')
      return
    }
    setCreating(true)
    setError('')
    try {
      const result = await api.createProjectToken(projectId, {
        name: trimmed,
        scopes: preset.scopes,
      })
      setTokens((prev) => [result.token, ...prev])
      setCreated(result)
      setCopied('')
      setName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成令牌失败')
    } finally {
      setCreating(false)
    }
  }

  const copy = async (
    kind: 'token' | 'row' | 'ai-row',
    text: string,
    rowId = '',
  ) => {
    const ok = await copyText(text)
    if (!ok) {
      setError('复制失败，请手动选择令牌明文')
      return
    }
    setError('')
    if (kind === 'row' || kind === 'ai-row') {
      setCopiedRow(`${rowId}${kind === 'ai-row' ? ':ai' : ''}`)
    } else {
      setCopied('token')
    }
  }

  const revoke = async (token: ProjectToken) => {
    if (revoking) return
    if (revokeId !== token.id) {
      setRevokeId(token.id)
      return
    }
    setRevoking(true)
    setError('')
    try {
      await api.revokeProjectToken(projectId, token.id)
      setTokens((prev) =>
        prev.map((item) =>
          item.id === token.id ? { ...item, status: 'revoked' } : item,
        ),
      )
      if (created?.token.id === token.id) setCreated(null)
      setRevokeId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '吊销令牌失败')
    } finally {
      setRevoking(false)
    }
  }

  const purge = async (token: ProjectToken) => {
    if (purging) return
    if (purgeId !== token.id) {
      setPurgeId(token.id)
      return
    }
    setPurging(true)
    setError('')
    try {
      await api.purgeProjectToken(projectId, token.id)
      setTokens((prev) => prev.filter((item) => item.id !== token.id))
      if (created?.token.id === token.id) setCreated(null)
      setPurgeId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除令牌失败')
    } finally {
      setPurging(false)
    }
  }

  const purgeAll = async () => {
    if (purgingAll) return
    if (!purgeAllArmed) {
      setPurgeAllArmed(true)
      return
    }
    setPurgingAll(true)
    setError('')
    try {
      await api.purgeRevokedProjectTokens(projectId)
      setTokens((prev) => prev.filter((item) => item.status === 'active'))
      setPurgeAllArmed(false)
      setPurgeId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '清理已失效令牌失败')
    } finally {
      setPurgingAll(false)
    }
  }

  return (
    <section className="token-section" aria-label="AI 接入令牌">
      <div className="token-section-head">
        <div>
          <h4>AI 接入令牌</h4>
          <p>
            调用 <code>/ingest/v1</code> 时放入{' '}
            <code>X-Project-Token</code> 请求头，每个客户端单独一枚；
            令牌明文保存在设置页，可随时复制；复制给 AI 会带入长期令牌，请勿粘贴到不可信对话。
          </p>
        </div>
        <div className="token-head-actions">
          {inactiveCount > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              disabled={purgingAll}
              onClick={() => void purgeAll()}
            >
              {purgeAllArmed
                ? `确认清理 ${inactiveCount} 枚`
                : `清理已失效 ${inactiveCount} 枚`}
            </button>
          )}
          <span className="token-count">{activeCount} 枚有效</span>
        </div>
      </div>

      <div className="token-create">
        <input
          value={name}
          placeholder="令牌名称，如 AI 测试机"
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              void create()
            }
          }}
        />
        <select
          value={presetId}
          onChange={(event) => setPresetId(event.target.value)}
          disabled={!meta}
        >
          {(meta?.presets ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-primary btn-xs"
          onClick={() => void create()}
          disabled={creating || !name.trim() || !preset}
        >
          {creating ? '生成中…' : '生成令牌'}
        </button>
      </div>
      {preset && <p className="token-hint">{preset.hint}</p>}
      {created && (
        <div className="token-secret">
          <div className="token-secret-head">
            <strong>令牌已生成，列表可随时查看</strong>
            <span>{created.token.name}</span>
          </div>
          <code>{created.secret}</code>
          <div className="token-secret-actions">
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => void copy('token', created.secret)}
            >
              <Icon name={copied === 'token' ? 'check' : 'copy'} size={13} />
              {copied === 'token' ? '已复制' : '复制令牌'}
            </button>
          </div>
        </div>
      )}

      {error && <p className="dialog-error">{error}</p>}

      {loading ? (
        <p className="token-hint">正在读取接入令牌…</p>
      ) : tokens.length === 0 ? (
        <p className="token-hint">
          还没有接入令牌，生成后把明文交给对应的 AI 或 CI。
        </p>
      ) : (
        <div className="token-list">
          {tokens.map((token) => (
            <div className="token-row" key={token.id}>
              <div className="token-meta">
                <span className="token-title">
                  <strong>{token.name}</strong>
                  {token.token ? (
                    <code className="token-plain">{token.token}</code>
                  ) : (
                    <code>{token.prefix}…（历史令牌不可查看）</code>
                  )}
                </span>
                <span className="token-scopes">
                  {token.scopes
                    .map((scope) => scopeLabels[scope] ?? scope)
                    .join(' · ')}
                </span>
                <span className="token-dates">
                  创建 {formatDateTime(token.createdAt)}
                  {token.lastUsedAt
                    ? ` · 最近使用 ${formatDateTime(token.lastUsedAt)}`
                    : ' · 尚未使用'}
                </span>
              </div>
              <div className="token-row-actions">
                {token.token && (
                  <>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => void copy('row', token.token ?? '')}
                    >
                      <Icon name={copiedRow === token.id ? 'check' : 'copy'} size={13} />
                      {copiedRow === token.id ? '已复制' : '复制令牌'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      title="复制内容包含长期令牌，请勿粘贴到不可信的 AI 对话或公开日志"
                      onClick={() => void copy('ai-row', buildAiPrompt(token.token ?? '', token.scopes), token.id)}
                    >
                      <Icon name={copiedRow === `${token.id}:ai` ? 'check' : 'copy'} size={13} />
                      {copiedRow === `${token.id}:ai` ? '已复制' : '复制给 AI'}
                    </button>
                  </>
                )}
                <span className={`token-status token-status-${token.status}`}>
                  {STATUS_LABELS[token.status]}
                </span>
                {token.status === 'active' ? (
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    disabled={revoking}
                    onClick={() => void revoke(token)}
                  >
                    {revokeId === token.id ? '确认吊销' : '吊销'}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    disabled={purging}
                    onClick={() => void purge(token)}
                  >
                    {purgeId === token.id ? '确认删除' : '删除'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
