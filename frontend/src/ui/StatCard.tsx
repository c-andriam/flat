import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { Skeleton } from './Skeleton'

export type StatTone = 'blue' | 'green' | 'orange' | 'red' | 'purple' | 'neutral'

const ICON_TONES: Record<StatTone, string> = {
  blue: 'bg-accent-subtle text-accent',
  green: 'bg-success-subtle text-success',
  orange: 'bg-warning-subtle text-warning',
  red: 'bg-danger-subtle text-danger',
  purple: 'bg-info-subtle text-info',
  neutral: 'bg-inset text-fg-muted',
}

const VALUE_TONES: Record<StatTone, string> = {
  blue: 'text-fg',
  green: 'text-fg',
  orange: 'text-warning',
  red: 'text-danger',
  purple: 'text-fg',
  neutral: 'text-fg',
}

export interface StatCardProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  tone?: StatTone
  hint?: ReactNode
  loading?: boolean
  compact?: boolean
  className?: string
}

export function StatCard({
  label,
  value,
  icon,
  tone = 'blue',
  hint,
  loading = false,
  compact = false,
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        'rounded-[8px] border border-line bg-surface text-left',
        'transition-[border-color,box-shadow,background-color] duration-200',
        'hover:border-fg-subtle hover:shadow-raised',
        compact ? 'p-4' : 'p-5',
        className,
      )}
    >
      {icon ? (
        <div
          className={cn(
            'mb-3.5 flex h-9 w-9 items-center justify-center rounded-[8px]',
            ICON_TONES[tone],
          )}
        >
          {icon}
        </div>
      ) : null}

      <div className="mb-1 text-[12px] font-medium uppercase tracking-[0.04em] text-fg-muted">
        {label}
      </div>

      {loading ? (
        <Skeleton className={compact ? 'h-7 w-16' : 'h-8 w-20'} />
      ) : (
        <div
          className={cn(
            'font-bold leading-[1.2] tracking-[-0.03em]',
            compact ? 'text-2xl' : 'text-[28px]',
            VALUE_TONES[tone],
          )}
        >
          {value}
        </div>
      )}

      {hint ? <div className="mt-1.5 text-[12px] text-fg-subtle">{hint}</div> : null}
    </div>
  )
}

export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('grid w-full grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {children}
    </div>
  )
}
