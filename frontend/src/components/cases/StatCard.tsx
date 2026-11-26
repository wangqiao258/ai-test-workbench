import { percent } from '../../utils/format'
import { Icon, type IconName } from '../ui'

interface StatCardProps {
  label: string
  value: string
  hint: string
  progress?: number
  icon: IconName
}

export function StatCard({ label, value, hint, progress, icon }: StatCardProps) {
  return (
    <div className="stat-card">
      <div className="stat-card-head">
        <span>{label}</span>
        <span className="stat-icon">
          <Icon name={icon} size={15} />
        </span>
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint">{hint}</div>
      {typeof progress === 'number' && (
        <div className="stat-track" aria-hidden="true">
          <span style={{ width: percent(progress) }} />
        </div>
      )}
    </div>
  )
}
