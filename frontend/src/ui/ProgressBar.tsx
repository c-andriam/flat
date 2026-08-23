import { cn } from '@/lib/cn'

export interface ProgressBarProps {
  /** Avancement de 0 à 100. */
  value: number
  tone?: 'accent' | 'success' | 'warning' | 'danger'
  showValue?: boolean
  className?: string
}

const TONES = {
  accent: 'bg-accent',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
} as const

export function ProgressBar({ value, tone = 'accent', showValue = true, className }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div
        className="h-1.5 min-w-16 flex-1 overflow-hidden rounded-full bg-inset"
        role="progressbar"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn('h-full rounded-full transition-[width] duration-500', TONES[tone])}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showValue ? (
        <span className="w-9 shrink-0 text-right text-[11px] font-semibold tabular-nums text-fg-muted">
          {Math.round(clamped)}%
        </span>
      ) : null}
    </div>
  )
}
