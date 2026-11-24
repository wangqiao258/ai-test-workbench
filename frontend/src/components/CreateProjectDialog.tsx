import { useEffect, useState, type FormEvent } from 'react'
import type { CreateProjectInput } from '../services/api'
import { Icon } from './ui'

interface Props {
  open: boolean
  onCancel: () => void
  onSubmit: (input: CreateProjectInput) => Promise<void>
}

const KEY_PATTERN = /^[a-z0-9][a-z0-9-]{1,63}$/

export function CreateProjectDialog({ open, onCancel, onSubmit }: Props) {
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [repo, setRepo] = useState('')
  const [environment, setEnvironment] = useState('')
  const [owner, setOwner] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setKey('')
    setName('')
    setRepo('')
    setEnvironment('')
    setOwner('')
    setError('')
    setLoading(false)
  }, [open])

  if (!open) return null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (loading) return

    const normalizedKey = key.trim().toLowerCase()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('请填写项目名称')
      return
    }
    if (!KEY_PATTERN.test(normalizedKey)) {
      setError('项目 KEY 需为 2-64 位小写字母、数字或连字符，且以字母或数字开头')
      return
    }

    setLoading(true)
    setError('')
    try {
      await onSubmit({
        key: normalizedKey,
        name: trimmedName,
        repo: repo.trim(),
        environment: environment.trim(),
        owner: owner.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建项目失败')
      setLoading(false)
    }
  }

  return (
    <div className="dialog-backdrop" onMouseDown={loading ? undefined : onCancel}>
      <form
        className="dialog dialog-project"
        role="dialog"
        aria-modal="true"
        aria-label="新建项目"
        onSubmit={submit}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-primary">
            <Icon name="plus" size={18} />
          </span>
          <div>
            <h3>新建项目</h3>
            <p>创建后你将成为该项目的管理员，需求、运行与缺陷与其他项目完全隔离。</p>
          </div>
        </div>

        <div className="form-grid">
          <label className="form-field">
            <span>项目名称 *</span>
            <input
              autoFocus
              value={name}
              placeholder="交易服务"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>项目 KEY *</span>
            <input
              value={key}
              placeholder="shop-api"
              spellCheck={false}
              onChange={(event) => setKey(event.target.value)}
            />
            <em>小写字母、数字或连字符，创建后不可修改</em>
          </label>
          <label className="form-field">
            <span>仓库</span>
            <input
              value={repo}
              placeholder="shop/shop-api"
              onChange={(event) => setRepo(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>环境</span>
            <input
              value={environment}
              placeholder="staging-cn-east"
              onChange={(event) => setEnvironment(event.target.value)}
            />
          </label>
          <label className="form-field form-field-wide">
            <span>负责人</span>
            <input
              value={owner}
              placeholder="交易产品组"
              onChange={(event) => setOwner(event.target.value)}
            />
          </label>
        </div>

        {error && <p className="dialog-error">{error}</p>}

        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={loading}>
            取消
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !key.trim() || !name.trim()}
          >
            {loading ? '创建中…' : '创建项目'}
          </button>
        </div>
      </form>
    </div>
  )
}
