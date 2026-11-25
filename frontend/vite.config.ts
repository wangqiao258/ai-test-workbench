import { execFileSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * 版本号唯一来源是 git tag（如 v0.2.0）。
 * - 当前提交正好在 tag 上：0.2.0
 * - tag 之后有提交：0.2.0+3.68e5b8e
 * - 工作区有未提交改动：追加 .dirty
 * 无 git 环境时可用 APP_VERSION 环境变量覆盖，否则退化为 0.0.0+unknown。
 */
function buildVersion(): string {
  const override = process.env.APP_VERSION?.trim()
  if (override) return override.replace(/^v/, '')
  try {
    const raw = execFileSync('git', ['describe', '--tags', '--always', '--dirty'], {
      cwd: process.cwd(),
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
    const matched = /^v?(\d+\.\d+\.\d+)(?:-(\d+)-g([0-9a-f]+))?(-dirty)?$/.exec(raw)
    if (!matched) return raw.replace(/^v/, '')
    const [, base, ahead, sha, dirty] = matched
    if (!sha) return `${base}${dirty ? '+dirty' : ''}`
    return `${base}+${ahead}.${sha}${dirty ? '.dirty' : ''}`
  } catch {
    return '0.0.0+unknown'
  }
}

const VIRTUAL_VERSION_ID = 'virtual:app-version'
const RESOLVED_VERSION_ID = '\0' + VIRTUAL_VERSION_ID

/** 通过虚拟模块向源码提供版本号，dev 与 build 行为一致。 */
function appVersionPlugin() {
  return {
    name: 'app-version',
    resolveId(id: string) {
      if (id === VIRTUAL_VERSION_ID) return RESOLVED_VERSION_ID
      return null
    },
    load(id: string) {
      if (id === RESOLVED_VERSION_ID) {
        return `export const APP_VERSION = ${JSON.stringify(buildVersion())}`
      }
      return null
    },
  }
}

export default defineConfig({
  plugins: [react(), appVersionPlugin()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
