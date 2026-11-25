import { useEffect, useState } from 'react'
import { DialogShell } from './ui'

interface Props {
  open: boolean
  onCancel: () => void
  onSubmit: (currentPassword: string, newPassword: string) => Promise<void>
}

export function ChangePasswordDialog({ open, onCancel, onSubmit }: Props) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError('')
    setLoading(false)
  }, [open])

  const submit = async () => {
    if (loading) return

    if (newPassword.length < 8) {
      setError('新密码至少 8 位')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }
    if (newPassword === currentPassword) {
      setError('新密码不能与当前密码相同')
      return
    }

    setLoading(true)
    setError('')
    try {
      await onSubmit(currentPassword, newPassword)
    } catch (err) {
      setError(err instanceof Error ? err.message : '修改密码失败')
      setLoading(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="修改密码"
      description="修改成功后需要使用新密码重新登录。"
      icon="shield"
      busy={loading}
      error={error}
      submitText="修改密码"
      canSubmit={Boolean(currentPassword && newPassword && confirmPassword)}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field form-field-wide">
          <span>当前密码</span>
          <input
            autoFocus
            type="password"
            value={currentPassword}
            autoComplete="current-password"
            placeholder="请输入当前密码"
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>新密码</span>
          <input
            type="password"
            value={newPassword}
            autoComplete="new-password"
            placeholder="至少 8 位"
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>确认新密码</span>
          <input
            type="password"
            value={confirmPassword}
            autoComplete="new-password"
            placeholder="再次输入新密码"
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </label>
      </div>
    </DialogShell>
  )
}
