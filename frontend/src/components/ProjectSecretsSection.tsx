import { useEffect, useMemo, useState } from 'react'
import type { ProjectSecret } from '../types'
import { api } from '../services/api'
import { formatDateTime } from '../utils/format'
import { Icon } from './ui'

interface Props {
  projectId: string
  canEdit: boolean
}

type SecretKind = 'account' | 'token' | 'custom'

const KIND_OPTIONS: { id: SecretKind; label: string }[] = [
  { id: 'account', label: '账号密码' },
  { id: 'token', label: 'Token' },
  { id: 'custom', label: '自定义' },
]

const GROUP_SUFFIXES = [
  { suffix: '_USERNAME', label: '账号' },
  { suffix: '_PASSWORD', label: '密码' },
  { suffix: '_TOKEN', label: 'Token' },
]
const FIELD_ORDER = GROUP_SUFFIXES.map((item) => item.label)

const CUSTOM_KEY_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/
const PREFIX_PATTERN = /^[A-Z][A-Z0-9_]{0,54}$/

interface SecretCard {
  id: string
  description: string
  fields: { secret: ProjectSecret; label: string }[]
}

function fieldRank(label: string): number {
  const index = FIELD_ORDER.indexOf(label)
  return index === -1 ? FIELD_ORDER.length : index
}

function buildCards(secrets: ProjectSecret[]): SecretCard[] {
  const cards = new Map<string, SecretCard>()
  for (const secret of secrets) {
    const matched = GROUP_SUFFIXES.find(
      (item) =>
        secret.key.endsWith(item.suffix) &&
        secret.key.length > item.suffix.length,
    )
    const id = matched ? secret.key.slice(0, -matched.suffix.length) : secret.key
    const label = matched ? matched.label : '值'
    const card = cards.get(id)
    if (card) {
      card.fields.push({ secret, label })
      if (!card.description) card.description = secret.description
    } else {
      cards.set(id, {
        id,
        description: secret.description,
        fields: [{ secret, label }],
      })
    }
  }
  for (const card of cards.values()) {
    card.fields.sort((a, b) => fieldRank(a.label) - fieldRank(b.label))
  }
  return [...cards.values()].sort((a, b) => a.id.localeCompare(b.id))
}

export function ProjectSecretsSection({ projectId, canEdit }: Props) {
  const [secrets, setSecrets] = useState<ProjectSecret[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [kind, setKind] = useState<SecretKind>('account')
  const [prefix, setPrefix] = useState('')
  const [label, setLabel] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const [customKey, setCustomKey] = useState('')
  const [customValue, setCustomValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleteCard, setDeleteCard] = useState('')
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    api
      .listProjectSecrets(projectId)
      .then((rows) => {
        if (alive) setSecrets(rows)
      })
      .catch((err) => {
        if (alive) {
          setError(err instanceof Error ? err.message : '读取测试凭据失败')
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [projectId])

  const cards = useMemo(() => buildCards(secrets), [secrets])
  const normalizedPrefix = prefix.trim().toUpperCase()
  const previewKeys =
    kind === 'custom' || !PREFIX_PATTERN.test(normalizedPrefix)
      ? []
      : kind === 'account'
        ? [`${normalizedPrefix}_USERNAME`, `${normalizedPrefix}_PASSWORD`]
        : [`${normalizedPrefix}_TOKEN`]

  const save = async () => {
    if (saving) return
    setError('')
    setNotice('')
    const description = label.trim()
    let rows: { key: string; value: string }[]
    if (kind === 'custom') {
      const normalized = customKey.trim().toUpperCase()
      if (!CUSTOM_KEY_PATTERN.test(normalized)) {
        setError('名称只能包含大写字母、数字和下划线，且以字母开头')
        return
      }
      if (!customValue) {
        setError('请填写凭据值')
        return
      }
      rows = [{ key: normalized, value: customValue }]
    } else {
      if (!PREFIX_PATTERN.test(normalizedPrefix)) {
        setError('标识只能包含大写字母、数字和下划线，以字母开头，最长 55 个字符')
        return
      }
      if (kind === 'account') {
        if (!username.trim()) {
          setError('请填写账号')
          return
        }
        if (!password) {
          setError('请填写密码')
          return
        }
        rows = [
          { key: `${normalizedPrefix}_USERNAME`, value: username.trim() },
          { key: `${normalizedPrefix}_PASSWORD`, value: password },
        ]
      } else {
        if (!token) {
          setError('请填写 Token')
          return
        }
        rows = [{ key: `${normalizedPrefix}_TOKEN`, value: token }]
      }
    }

    setSaving(true)
    try {
      const saved: ProjectSecret[] = []
      for (const row of rows) {
        saved.push(
          await api.upsertProjectSecret(projectId, row.key, {
            value: row.value,
            description,
          }),
        )
      }
      setSecrets((prev) => {
        const map = new Map(prev.map((item) => [item.key, item]))
        for (const item of saved) map.set(item.key, item)
        return [...map.values()].sort((a, b) => a.key.localeCompare(b.key))
      })
      setNotice(`已保存 ${saved.map((item) => item.key).join('、')}`)
      setPrefix('')
      setLabel('')
      setUsername('')
      setPassword('')
      setToken('')
      setCustomKey('')
      setCustomValue('')
      setDeleteCard('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存测试凭据失败')
    } finally {
      setSaving(false)
    }
  }

  const removeCard = async (card: SecretCard) => {
    if (deleting) return
    if (deleteCard !== card.id) {
      setDeleteCard(card.id)
      return
    }
    setDeleting(true)
    setError('')
    setNotice('')
    try {
      for (const field of card.fields) {
        await api.deleteProjectSecret(projectId, field.secret.key)
      }
      const removed = new Set(card.fields.map((field) => field.secret.key))
      setSecrets((prev) => prev.filter((item) => !removed.has(item.key)))
      setDeleteCard('')
      setNotice(`已删除 ${card.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除测试凭据失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section className="token-section" aria-label="测试凭据">
      <div className="token-section-head">
        <div>
          <h4>测试凭据</h4>
          <p>
            被测系统的账号、密码或 Token。按凭据卡片录入，值加密保存、不回显；
            pytest 插件运行时注入环境变量。
          </p>
        </div>
        <span className="token-count">{cards.length} 项</span>
      </div>

      {canEdit && (
        <div className="form-grid">
          <label className="form-field">
            <span>类型</span>
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as SecretKind)}
            >
              {KIND_OPTIONS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {kind === 'custom' ? (
            <label className="form-field">
              <span>名称</span>
              <input
                value={customKey}
                placeholder="SUT_TOKEN"
                spellCheck={false}
                onChange={(event) => setCustomKey(event.target.value)}
              />
            </label>
          ) : (
            <label className="form-field">
              <span>标识</span>
              <input
                value={prefix}
                placeholder="ADMIN"
                spellCheck={false}
                onChange={(event) => setPrefix(event.target.value)}
              />
            </label>
          )}
          {kind === 'account' && (
            <>
              <label className="form-field">
                <span>账号</span>
                <input
                  value={username}
                  placeholder="admin"
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setUsername(event.target.value)}
                />
              </label>
              <label className="form-field">
                <span>密码</span>
                <input
                  type="password"
                  value={password}
                  placeholder="密码"
                  autoComplete="new-password"
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
            </>
          )}
          {kind === 'token' && (
            <label className="form-field form-field-wide">
              <span>Token</span>
              <input
                type="password"
                value={token}
                placeholder="Token"
                autoComplete="new-password"
                onChange={(event) => setToken(event.target.value)}
              />
            </label>
          )}
          {kind === 'custom' && (
            <label className="form-field">
              <span>值</span>
              <input
                type="password"
                value={customValue}
                placeholder="Token、密码或账号"
                autoComplete="new-password"
                onChange={(event) => setCustomValue(event.target.value)}
              />
            </label>
          )}
          <label className="form-field form-field-wide">
            <span>用途</span>
            <input
              value={label}
              placeholder="如：管理员账号，密码不要写在这里"
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
        </div>
      )}
      {canEdit && (
        <div className="token-create">
          <button
            type="button"
            className="btn btn-primary btn-xs"
            onClick={() => void save()}
            disabled={saving}
          >
            <Icon name="check" size={13} />
            {saving ? '保存中…' : '保存凭据'}
          </button>
        </div>
      )}

      <p className="token-hint">
        {previewKeys.length > 0
          ? `将写入 ${previewKeys.join('、')}；pytest 用 os.environ['${previewKeys[0]}'] 引用。`
          : "pytest 用例用 os.environ['KEY']，Tavern 用例用 {tavern.env_vars.KEY} 引用，不要把值写进 YAML 或代码。"}
      </p>

      {error && <p className="dialog-error">{error}</p>}
      {notice && <p className="token-hint">{notice}</p>}

      {loading ? (
        <p className="token-hint">正在读取测试凭据…</p>
      ) : cards.length === 0 ? (
        <p className="token-hint">还没有配置测试凭据。</p>
      ) : (
        <div className="token-list">
          {cards.map((card) => {
            const updatedAt = card.fields
              .map((field) => field.secret.updatedAt)
              .sort()
              .pop()
            const lastUsed = card.fields
              .map((field) => field.secret.lastUsedAt)
              .filter((value): value is string => Boolean(value))
              .sort()
              .pop()
            const expired = card.fields.some((field) => field.secret.expired)
            return (
              <div className="secret-card" key={card.id}>
                <div className="secret-card-head">
                  <div className="token-meta">
                    <span className="token-title">
                      <strong>{card.id}</strong>
                      {card.description && (
                        <span className="token-scopes">{card.description}</span>
                      )}
                      {expired && <span className="warn-chip">已过期</span>}
                    </span>
                    <span className="token-dates">
                      更新 {formatDateTime(updatedAt ?? '')}
                      {lastUsed
                        ? ` · 最近读取 ${formatDateTime(lastUsed)}`
                        : ' · 尚未读取'}
                    </span>
                  </div>
                  {canEdit && (
                    <div className="token-row-actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        disabled={deleting}
                        onClick={() => void removeCard(card)}
                      >
                        {deleteCard === card.id ? '确认删除' : '删除'}
                      </button>
                    </div>
                  )}
                </div>
                <div className="secret-card-fields">
                  {card.fields.map((field) => (
                    <div className="secret-field" key={field.secret.key}>
                      <span className="secret-field-label">{field.label}</span>
                      <code>{field.secret.key}</code>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
