import { useEffect, useState } from 'react'
import type { CreateRunRequestInput } from '../services/api'
import { DialogShell } from './ui'

interface Props {
  open: boolean
  caseNodeids?: string[]
  onCancel: () => void
  onSubmit: (input: CreateRunRequestInput) => Promise<void>
}

export function RunRequestDialog({
  open,
  caseNodeids,
  onCancel,
  onSubmit,
}: Props) {
  const selected = caseNodeids ?? []
  const isSelection = selected.length > 0
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

  const submit = async () => {
    if (loading) return

    const specPaths = specs
      .split(/[\n,]/)
      .map((item) => item.trim())
      .filter(Boolean)

    setLoading(true)
    setError('')
    try {
      await onSubmit(
        isSelection
          ? { reason: reason.trim(), caseNodeids: selected }
          : { reason: reason.trim(), specPaths },
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建运行任务失败')
      setLoading(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title={isSelection ? '运行选定用例' : '运行测试'}
      description={
        isSelection
          ? `将精确执行选中的 ${selected.length} 条用例，不再按文件或目录展开。`
          : '平台只创建运行任务，由 Runner 拉取后执行 pytest，并把用例结果与 HAR 自动回传。'
      }
      icon="play"
      className="dialog-project"
      busy={loading}
      busyText="创建中…"
      error={error}
      submitText="开始执行"
      onCancel={onCancel}
      onSubmit={submit}
    >
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
        {isSelection ? (
          <div className="dialog-note">
            已选 {selected.length} 条用例；执行范围以触发时的 nodeid 快照为准。
          </div>
        ) : (
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
        )}
      </div>

      <p className="dialog-note">同一项目同时只能有一个待执行或执行中的任务。</p>
    </DialogShell>
  )
}
