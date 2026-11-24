import { useEffect, useState, type FormEvent } from 'react'
import type { CreateRunRequestInput } from '../services/api'
import { Icon } from './ui'

interface Props {
  open: boolean
  onCancel: () => void
  onSubmit: (input: CreateRunRequestInput) => Promise<void>
}

export function RunRequestDialog({ open, onCancel, onSubmit }: Props) {
  const [reason, setReason] = useState('')
  const [specs, setSpecs] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setReason('')
    setSpecs('')
    setError('')
    setLoading(false)
  }, [open])

  if (!open) return null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (loading) return

    const specPaths = specs
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)

    setLoading(true)
    setError('')
    try {
      await onSubmit({ reason: reason.trim(), specPaths })
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建运行任务失败')
      setLoading(false)
    }
  }

  return (
    <div className="dialog-backdrop" onMouseDown={loading ? undefined : onCancel}>
      <form
        className="dialog dialog-project"
        role="dialog"
        aria-modal="true"
        aria-label="运行测试"
        onSubmit={submit}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-primary">
            <Icon name="play" size={18} />
          </span>
          <div>
            <h3>运行测试</h3>
            <p>
              平台只创建运行任务，由 Runner
              拉取后执行 pytest，并把用例结果与 HAR 自动回传。
            </p>
          </div>
        </div>

        <div className="form-grid">
          <label className="form-field form-field-wide">
            <span>运行说明</span>
            <input
              autoFocus
              value={reason}
              maxLength={255}
              placeholder="例如：订单回归 / 发布前全量"
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label className="form-field form-field-wide">
            <span>用例路径</span>
            <textarea
              className="textarea"
              rows={3}
              value={specs}
              spellCheck={false}
              placeholder="例如：smoke/order.tavern.yaml"
              onChange={(event) => setSpecs(event.target.value)}
            />
            <em>留空则执行 specs 目录下的全部用例</em>
          </label>
        </div>

        <p className="dialog-note">
          同一项目同时只能有一个待执行或执行中的任务。
        </p>

        {error && <p className="dialog-error">{error}</p>}

        <div className="dialog-actions">
          <button
            type="button"
            className="btn"
            onClick={onCancel}
            disabled={loading}
          >
            取消
          </button>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? '创建中…' : '开始执行'}
          </button>
        </div>
      </form>
    </div>
  )
}
