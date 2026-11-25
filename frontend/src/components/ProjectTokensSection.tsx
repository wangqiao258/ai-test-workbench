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
  const [copied, setCopied] = useState<'token' | 'curl' | ''>('')
  const [revokeId, setRevokeId] = useState<string | null>(null)
  const [revoking, setRevoking] = useState(false)

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
  const curl = created
    ? `curl -H "X-Project-Token: ${created.secret}" ${window.location.origin}/ingest/v1/whoami`
    : ''

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

  const copy = async (kind: 'token' | 'curl', text: string) => {
    const ok = await copyText(text)
    if (ok) {
      setCopied(kind)
      setError('')
    } else {
      setError('复制失败，请手动选择令牌明文')
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

  return (
    <section className="token-section" aria-label="AI 接入令牌">
      <div className="token-section-head">
        <div>
          <h4>AI 接入令牌</h4>
          <p>
            调用 <code>/ingest/v1</code> 时放入{' '}
            <code>X-Project-Token</code> 请求头，每个客户端单独一枚。
          </p>
        </div>
        <span className="token-count">{activeCount} 枚有效</span>
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
            <strong>令牌已生成，仅显示一次</strong>
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
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={() => void copy('curl', curl)}
            >
              <Icon name={copied === 'curl' ? 'check' : 'copy'} size={13} />
              {copied === 'curl' ? '已复制' : '复制 curl'}
            </button>
          </div>
          <pre className="token-curl">{curl}</pre>
        </div>
      )}

      {error && <p className="dialog-error">{error}</p>}

      {loading ? (
        <p className="token-hint">正在读取接入令牌…</p>
      ) : tokens.length === 0 ? (
        <p className="token-hint">
          还没有接入令牌，生成后把明文交给对应的 AI、Runner 或 CI。
        </p>
      ) : (
        <div className="token-list">
          {tokens.map((token) => (
            <div className="token-row" key={token.id}>
              <div className="token-meta">
                <span className="token-title">
                  <strong>{token.name}</strong>
                  <code>{token.prefix}…</code>
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
                <span className={`token-status token-status-${token.status}`}>
                  {STATUS_LABELS[token.status]}
                </span>
                {token.status === 'active' && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    disabled={revoking}
                    onClick={() => void revoke(token)}
                  >
                    {revokeId === token.id ? '确认吊销' : '吊销'}
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
