import { useEffect, useState } from 'react'
import type { ProjectSecret } from '../types'
import { api } from '../services/api'
import { formatDateTime } from '../utils/format'
import { Icon } from './ui'

interface Props {
  projectId: string
  canEdit: boolean
}

export function ProjectSecretsSection({ projectId, canEdit }: Props) {
  const [secrets, setSecrets] = useState<ProjectSecret[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleteKey, setDeleteKey] = useState('')
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

  const save = async () => {
    if (saving) return
    const normalized = key.trim().toUpperCase()
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(normalized)) {
      setError('名称只能包含大写字母、数字和下划线，且以字母开头')
      return
    }
    if (!value) {
      setError('请填写凭据值')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const saved = await api.upsertProjectSecret(projectId, normalized, {
        value,
        description: description.trim(),
      })
      setSecrets((prev) => {
        const rest = prev.filter((item) => item.key !== saved.key)
        return [...rest, saved].sort((a, b) => a.key.localeCompare(b.key))
      })
      setKey('')
      setValue('')
      setDescription('')
      setNotice(`已保存 ${saved.key}，pytest 用例用 os.environ['${saved.key}'] 引用`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存测试凭据失败')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (item: ProjectSecret) => {
    if (deleting) return
    if (deleteKey !== item.key) {
      setDeleteKey(item.key)
      return
    }
    setDeleting(true)
    setError('')
    setNotice('')
    try {
      await api.deleteProjectSecret(projectId, item.key)
      setSecrets((prev) => prev.filter((row) => row.key !== item.key))
      setDeleteKey('')
      setNotice(`已删除 ${item.key}`)
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
            被测系统的账号、密码或 Token。值加密保存，保存后不回显；
            pytest 插件运行时注入环境变量。
          </p>
        </div>
        <span className="token-count">{secrets.length} 项</span>
      </div>

      {canEdit && (
        <div className="form-grid">
          <label className="form-field">
            <span>名称</span>
            <input
              value={key}
              placeholder="SUT_TOKEN"
              spellCheck={false}
              onChange={(event) => setKey(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>值</span>
            <input
              type="password"
              value={value}
              placeholder="Token、密码或账号"
              autoComplete="new-password"
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <label className="form-field form-field-wide">
            <span>说明</span>
            <input
              value={description}
              placeholder="用途，如：测试账号 A"
              onChange={(event) => setDescription(event.target.value)}
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
        pytest 用例用 <code>os.environ['SUT_TOKEN']</code>，Tavern 用例用{' '}
        <code>{'{tavern.env_vars.SUT_TOKEN}'}</code> 引用，不要把值写进 YAML 或代码。
      </p>

      {error && <p className="dialog-error">{error}</p>}
      {notice && <p className="token-hint">{notice}</p>}

      {loading ? (
        <p className="token-hint">正在读取测试凭据…</p>
      ) : secrets.length === 0 ? (
        <p className="token-hint">还没有配置测试凭据。</p>
      ) : (
        <div className="token-list">
          {secrets.map((item) => (
            <div className="token-row" key={item.key}>
              <div className="token-meta">
                <span className="token-title">
                  <strong>{item.key}</strong>
                  {item.expired && <span className="warn-chip">已过期</span>}
                </span>
                <span className="token-scopes">
                  {item.description || '未填写说明'}
                </span>
                <span className="token-dates">
                  更新 {formatDateTime(item.updatedAt)}
                  {item.lastUsedAt
                    ? ` · 最近读取 ${formatDateTime(item.lastUsedAt)}`
                    : ' · 尚未读取'}
                </span>
              </div>
              {canEdit && (
                <div className="token-row-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    disabled={deleting}
                    onClick={() => void remove(item)}
                  >
                    {deleteKey === item.key ? '确认删除' : '删除'}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
