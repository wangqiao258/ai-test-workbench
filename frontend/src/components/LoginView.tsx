import { useState, type FormEvent } from 'react'

interface Props {
  loading: boolean
  error?: string
  onSubmit: (email: string, password: string) => Promise<void>
}

export function LoginView({ loading, error, onSubmit }: Props) {
  const [email, setEmail] = useState('tester@local')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (loading || !email.trim() || !password) return
    void onSubmit(email.trim(), password)
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div>
            <h1>AI 协同测试工作台</h1>
            <p>登录后按项目查看运行证据与人工审判</p>
          </div>
        </div>

        <label className="login-field">
          <span>邮箱</span>
          <input
            type="email"
            value={email}
            autoComplete="username"
            placeholder="tester@local"
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="login-field">
          <span>密码</span>
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            placeholder="请输入密码"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        {error && <p className="login-error">{error}</p>}

        <button
          type="submit"
          className="btn btn-primary btn-block"
          disabled={loading || !email.trim() || !password}
        >
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  )
}
